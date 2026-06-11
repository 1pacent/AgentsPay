// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/**
 * @title PaymentEscrow
 * @notice USDC escrow with state machine for agent-to-agent payments
 * @dev States: CREATED → FUNDED → DELIVERED → COMPLETED (or timeout → REFUNDED)
 *       Protocol fee: Tiered — $0.002 flat (≤$0.10), 1% ($0.10-$1.00), 0.5% ($1.00+)
 *       x402 bridge: initiateFromX402 accepts x402 payment receipts
 */
contract PaymentEscrow is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ──────────────────────────────────────────────
    // Constants
    // ──────────────────────────────────────────────

    /// @notice USDC has 6 decimal places
    uint256 public constant USDC_DECIMALS = 6;

    // ── Tiered fee structure ─────

    /// @notice Tier 1: flat $0.002 fee for orders ≤ $0.10 (100_000 in 6-dec USDC)
    uint256 public constant TIER1_MAX = 100_000;        // $0.10
    uint256 public constant TIER1_FEE_FLAT = 2_000;     // $0.002

    /// @notice Tier 2: 1% fee for orders between $0.10 and $1.00
    uint256 public constant TIER2_MAX = 1_000_000;      // $1.00
    uint256 public constant TIER2_FEE_BPS = 100;         // 1% = 100 bps

    /// @notice Tier 3: 0.5% fee for orders > $1.00
    uint256 public constant TIER3_FEE_BPS = 50;          // 0.5% = 50 bps

    /// @notice 100% = 10000 basis points
    uint256 public constant BPS_DENOMINATOR = 10000;

    /// @notice Default timeout durations (in seconds)
    uint256 public constant DEFAULT_BUYER_TIMEOUT = 6 hours;
    uint256 public constant DEFAULT_DELIVERY_TIMEOUT = 6 hours;

    // ──────────────────────────────────────────────
    // Types
    // ──────────────────────────────────────────────

    enum OrderState {
        CREATED,    // Order created, awaiting deposit
        FUNDED,     // USDC deposited into escrow
        DELIVERED,  // Seller marked as delivered, awaiting buyer verification
        COMPLETED,  // Buyer confirmed — payment released to seller
        REFUNDED,   // Timed out or cancelled — funds returned to buyer
        CANCELLED   // Cancelled before funding
    }

    struct Order {
        bytes32 orderId;
        address buyer;
        address seller;
        uint256 amount;         // USDC amount (6 decimals)
        uint256 feeAmount;      // Protocol fee deducted at release
        IERC20 token;           // USDC token contract
        OrderState state;
        uint256 createdAt;
        uint256 buyerTimeoutAt;     // Buyer must deposit by this time
        uint256 deliveryTimeoutAt;  // Buyer must verify by this time
    }

    // ──────────────────────────────────────────────
    // State
    // ──────────────────────────────────────────────

    /// @notice USDC token address (set once on deployment, or by owner)
    IERC20 public usdcToken;

    /// @notice Protocol fee accumulator
    uint256 public accumulatedFees;

    /// @notice Order ID → Order mapping
    mapping(bytes32 => Order) public orders;

    /// @notice Order IDs for enumeration
    bytes32[] public orderIds;

    // ── x402 bridge ─────

    /// @notice x402 payment receipt
    struct X402Receipt {
        address payer;
        address seller;
        uint256 amount;
        uint256 timestamp;
    }

    /// @notice Replay protection: x402 tx hash → used flag
    mapping(bytes32 => bool) public usedX402Receipts;

    /// @notice x402-originated order → receipt hash
    mapping(bytes32 => bytes32) public x402OrderReceipts;

    // ──────────────────────────────────────────────
    // Events
    // ──────────────────────────────────────────────

    event OrderCreated(
        bytes32 indexed orderId,
        address indexed buyer,
        address indexed seller,
        uint256 amount
    );

    event OrderFunded(
        bytes32 indexed orderId,
        address indexed buyer,
        uint256 amount
    );

    event DeliveryConfirmed(bytes32 indexed orderId);
    event PaymentReleased(bytes32 indexed orderId, address indexed seller, uint256 amount, uint256 fee);
    event OrderRefunded(bytes32 indexed orderId, address indexed buyer, uint256 amount);
    event OrderCancelled(bytes32 indexed orderId);
    event FeesWithdrawn(uint256 amount, address indexed to);
    event USDCUpdated(address indexed newToken);

    // ── x402 bridge events ──
    event X402OrderCreated(
        bytes32 indexed orderId,
        address indexed buyer,
        address indexed seller,
        uint256 amount,
        bytes32 x402TxHash
    );

    // ──────────────────────────────────────────────
    // Modifiers
    // ──────────────────────────────────────────────

    modifier onlyBuyer(bytes32 orderId) {
        require(orders[orderId].buyer == msg.sender, "PaymentEscrow: only buyer");
        _;
    }

    modifier onlySeller(bytes32 orderId) {
        require(orders[orderId].seller == msg.sender, "PaymentEscrow: only seller");
        _;
    }

    modifier inState(bytes32 orderId, OrderState expectedState) {
        require(orders[orderId].state == expectedState, "PaymentEscrow: invalid state");
        _;
    }

    // ──────────────────────────────────────────────
    // Constructor
    // ──────────────────────────────────────────────

    constructor(address _usdcToken) Ownable(msg.sender) {
        require(_usdcToken != address(0), "PaymentEscrow: invalid USDC address");
        usdcToken = IERC20(_usdcToken);
    }

    // ──────────────────────────────────────────────
    // Core Functions
    // ──────────────────────────────────────────────

    /**
     * @notice Create a new escrow order
     * @param orderId Unique identifier for the order (generated off-chain)
     * @param seller Address of the selling agent
     * @param amount USDC amount (6 decimals)
     * @param buyerTimeout Custom buyer deposit timeout (0 = use default)
     * @param deliveryTimeout Custom delivery timeout (0 = use default)
     */
    function createOrder(
        bytes32 orderId,
        address seller,
        uint256 amount,
        uint256 buyerTimeout,
        uint256 deliveryTimeout
    ) external nonReentrant returns (bool) {
        require(orderId != bytes32(0), "PaymentEscrow: invalid orderId");
        require(seller != address(0), "PaymentEscrow: invalid seller");
        require(seller != msg.sender, "PaymentEscrow: cannot self-order");
        require(amount > 0, "PaymentEscrow: amount must be > 0");
        require(orders[orderId].state == OrderState.CREATED || orders[orderId].createdAt == 0,
            "PaymentEscrow: order already exists");

        uint256 buyerTimeoutDuration = buyerTimeout > 0 ? buyerTimeout : DEFAULT_BUYER_TIMEOUT;

        orders[orderId] = Order({
            orderId: orderId,
            buyer: msg.sender,
            seller: seller,
            amount: amount,
            feeAmount: 0,
            token: usdcToken,
            state: OrderState.CREATED,
            createdAt: block.timestamp,
            buyerTimeoutAt: block.timestamp + buyerTimeoutDuration,
            deliveryTimeoutAt: 0  // Set when funded
        });

        orderIds.push(orderId);

        emit OrderCreated(orderId, msg.sender, seller, amount);
        return true;
    }

    /**
     * @notice Buyer deposits USDC into escrow
     * @dev Transfers USDC from buyer to this contract
     */
    function deposit(bytes32 orderId)
        external
        nonReentrant
        onlyBuyer(orderId)
        inState(orderId, OrderState.CREATED)
        returns (bool)
    {
        Order storage order = orders[orderId];

        require(block.timestamp < order.buyerTimeoutAt, "PaymentEscrow: buyer timeout expired");

        // Transfer USDC from buyer to this contract
        order.token.safeTransferFrom(msg.sender, address(this), order.amount);

        order.state = OrderState.FUNDED;
        order.deliveryTimeoutAt = block.timestamp + DEFAULT_DELIVERY_TIMEOUT;

        emit OrderFunded(orderId, msg.sender, order.amount);
        return true;
    }

    /**
     * @notice Seller confirms delivery has been completed
     * @dev Moves from FUNDED → DELIVERED
     */
    function confirmDelivery(bytes32 orderId)
        external
        nonReentrant
        onlySeller(orderId)
        inState(orderId, OrderState.FUNDED)
        returns (bool)
    {
        Order storage order = orders[orderId];
        order.state = OrderState.DELIVERED;

        emit DeliveryConfirmed(orderId);
        return true;
    }

    /**
     * @notice Buyer confirms delivery and releases payment to seller
     * @dev Transfers USDC minus protocol fee to seller
     */
    function releasePayment(bytes32 orderId)
        external
        nonReentrant
        onlyBuyer(orderId)
        inState(orderId, OrderState.DELIVERED)
        returns (bool)
    {
        Order storage order = orders[orderId];

        require(block.timestamp < order.deliveryTimeoutAt,
            "PaymentEscrow: delivery timeout expired - use refund");

        // Calculate protocol fee (tiered — using internal helper)
        uint256 fee = _calcFee(order.amount);
        uint256 sellerAmount = order.amount - fee;

        order.state = OrderState.COMPLETED;
        order.feeAmount = fee;
        accumulatedFees += fee;

        // Transfer seller amount
        order.token.safeTransfer(order.seller, sellerAmount);

        emit PaymentReleased(orderId, order.seller, sellerAmount, fee);
        return true;
    }

    /**
     * @notice Refund buyer after timeout
     * @dev Can be called by buyer after delivery timeout, or by anyone after delivery timeout
     */
    function refund(bytes32 orderId)
        external
        nonReentrant
        returns (bool)
    {
        Order storage order = orders[orderId];

        require(
            order.state == OrderState.FUNDED || order.state == OrderState.DELIVERED,
            "PaymentEscrow: refund not available"
        );

        if (order.state == OrderState.FUNDED) {
            // Buyer can refund within buyer timeout if seller hasn't delivered
            require(
                msg.sender == order.buyer,
                "PaymentEscrow: only buyer can refund FUNDED order"
            );
        }

        if (order.state == OrderState.DELIVERED) {
            // After delivery timeout, anyone can trigger refund
            require(
                block.timestamp >= order.deliveryTimeoutAt,
                "PaymentEscrow: delivery timeout not yet reached"
            );
        }

        order.state = OrderState.REFUNDED;

        // Return funds to buyer
        order.token.safeTransfer(order.buyer, order.amount);

        emit OrderRefunded(orderId, order.buyer, order.amount);
        return true;
    }

    /**
     * @notice Cancel order before funding
     */
    function cancelOrder(bytes32 orderId)
        external
        nonReentrant
        onlyBuyer(orderId)
        inState(orderId, OrderState.CREATED)
        returns (bool)
    {
        Order storage order = orders[orderId];
        order.state = OrderState.CANCELLED;

        emit OrderCancelled(orderId);
        return true;
    }

    // ──────────────────────────────────────────────
    // Fee Calculation
    // ──────────────────────────────────────────────

    /**
     * @notice Calculate protocol fee based on tiered structure
     * @param amount USDC amount (6 decimals)
     * @return fee Protocol fee in USDC (6 decimals)
     */
    function _calcFee(uint256 amount) private pure returns (uint256) {
        if (amount <= TIER1_MAX) {
            // Tier 1: flat $0.002 fee for microtransactions
            return TIER1_FEE_FLAT;
        } else if (amount <= TIER2_MAX) {
            // Tier 2: 1% for small transactions
            return (amount * TIER2_FEE_BPS) / BPS_DENOMINATOR;
        } else {
            // Tier 3: 0.5% for standard transactions
            return (amount * TIER3_FEE_BPS) / BPS_DENOMINATOR;
        }
    }

    /**
     * @notice Public wrapper for fee calculation (used by tests and external callers)
     */
    function calculateFee(uint256 amount) external pure returns (uint256) {
        return _calcFee(amount);
    }

    // ──────────────────────────────────────────────
    // x402 Bridge
    // ──────────────────────────────────────────────

    /**
     * @notice Create an escrow order from an x402 payment receipt
     * @dev x402 has already transferred USDC; this wraps it in escrow lifecycle
     * @param seller Address of the selling agent
     * @param x402TxHash x402 transaction hash (for replay protection)
     * @param amount USDC amount (6 decimals) that was paid via x402
     * @return orderId The escrow order ID
     */
    function initiateFromX402(
        address seller,
        bytes32 x402TxHash,
        uint256 amount
    ) external nonReentrant returns (bytes32 orderId) {
        require(seller != address(0), "PaymentEscrow: invalid seller");
        require(seller != msg.sender, "PaymentEscrow: cannot self-order");
        require(amount > 0, "PaymentEscrow: amount must be > 0");
        require(x402TxHash != bytes32(0), "PaymentEscrow: invalid x402 hash");
        require(!usedX402Receipts[x402TxHash], "PaymentEscrow: x402 receipt already used");

        // Mark receipt as used (replay protection)
        usedX402Receipts[x402TxHash] = true;

        // Generate order ID from the x402 receipt
        orderId = keccak256(abi.encodePacked("x402", x402TxHash, msg.sender, seller, amount, block.timestamp));

        require(orders[orderId].createdAt == 0, "PaymentEscrow: order ID collision");

        // Order starts in FUNDED state (x402 already transferred USDC)
        orders[orderId] = Order({
            orderId: orderId,
            buyer: msg.sender,
            seller: seller,
            amount: amount,
            feeAmount: 0,
            token: usdcToken,
            state: OrderState.FUNDED,
            createdAt: block.timestamp,
            buyerTimeoutAt: 0,
            deliveryTimeoutAt: block.timestamp + DEFAULT_DELIVERY_TIMEOUT
        });

        orderIds.push(orderId);
        x402OrderReceipts[orderId] = x402TxHash;

        emit X402OrderCreated(orderId, msg.sender, seller, amount, x402TxHash);

        return orderId;
    }

    // ──────────────────────────────────────────────
    // Query Functions
    // ──────────────────────────────────────────────

    function getOrder(bytes32 orderId) external view returns (Order memory) {
        require(orders[orderId].createdAt != 0, "PaymentEscrow: order not found");
        return orders[orderId];
    }

    function getOrderCount() external view returns (uint256) {
        return orderIds.length;
    }

    function getOrderState(bytes32 orderId) external view returns (OrderState) {
        require(orders[orderId].createdAt != 0, "PaymentEscrow: order not found");
        return orders[orderId].state;
    }

    // ──────────────────────────────────────────────
    // Admin Functions
    // ──────────────────────────────────────────────

    /**
     * @notice Owner withdraws accumulated protocol fees
     */
    function withdrawFees(address to) external onlyOwner nonReentrant {
        require(to != address(0), "PaymentEscrow: invalid address");
        uint256 amount = accumulatedFees;
        require(amount > 0, "PaymentEscrow: no fees to withdraw");

        accumulatedFees = 0;
        usdcToken.safeTransfer(to, amount);

        emit FeesWithdrawn(amount, to);
    }

    /**
     * @notice Owner can update USDC token address (e.g. mainnet swap)
     */
    function updateUSDC(address newToken) external onlyOwner {
        require(newToken != address(0), "PaymentEscrow: invalid address");
        usdcToken = IERC20(newToken);
        emit USDCUpdated(newToken);
    }
}
