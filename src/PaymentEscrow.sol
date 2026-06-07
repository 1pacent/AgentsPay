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
 *       Protocol fee: 0.5% (50 bps), paid by seller
 */
contract PaymentEscrow is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ──────────────────────────────────────────────
    // Constants
    // ──────────────────────────────────────────────

    /// @notice USDC has 6 decimal places
    uint256 public constant USDC_DECIMALS = 6;

    /// @notice Protocol fee: 0.5% = 50 basis points
    uint256 public constant PROTOCOL_FEE_BPS = 50;

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

        // Calculate protocol fee (0.5% paid by seller)
        uint256 fee = (order.amount * PROTOCOL_FEE_BPS) / BPS_DENOMINATOR;
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
