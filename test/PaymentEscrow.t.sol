// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/PaymentEscrow.sol";
import "../src/mock/MockUSDC.sol";

contract PaymentEscrowTest is Test {
    PaymentEscrow public escrow;
    MockUSDC public usdc;

    address public owner = address(0x100);
    address public buyer = address(0x200);
    address public seller = address(0x300);

    bytes32 constant ORDER_ID = keccak256("test-order-001");
    uint256 constant AMOUNT = 100_000_000; // 100 USDC (6 decimals)

    // x402 test constants
    bytes32 constant X402_TX_HASH = keccak256("x402-tx-001");

    function setUp() public {
        // Deploy mock USDC
        usdc = new MockUSDC();

        // Deploy escrow with mock USDC
        vm.prank(owner);
        escrow = new PaymentEscrow(address(usdc));

        // Mint USDC to buyer
        usdc.mint(buyer, AMOUNT * 10);

        // Approve escrow to spend buyer's USDC
        vm.prank(buyer);
        usdc.approve(address(escrow), AMOUNT * 10);
    }

    // ─── Happy Path ───

    function test_FullHappyPath() public {
        // 1. Create order
        vm.prank(buyer);
        bool created = escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
        assertTrue(created);

        // 2. Deposit
        vm.prank(buyer);
        bool funded = escrow.deposit(ORDER_ID);
        assertTrue(funded);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.FUNDED));

        // 3. Seller confirms delivery
        vm.prank(seller);
        bool confirmed = escrow.confirmDelivery(ORDER_ID);
        assertTrue(confirmed);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.DELIVERED));

        // 4. Buyer releases payment
        vm.prank(buyer);
        bool released = escrow.releasePayment(ORDER_ID);
        assertTrue(released);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.COMPLETED));

        // Check seller received 99.5 USDC (99_500_000)
        assertEq(usdc.balanceOf(seller), 99_500_000);

        // Check fees accumulated (0.5 USDC = 500_000)
        assertEq(escrow.accumulatedFees(), 500_000);
    }

    // ─── State Machine ───

    function test_Revert_DepositBeforeCreate() public {
        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: only buyer");
        escrow.deposit(ORDER_ID);
    }

    function test_Revert_DoubleDeposit() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);

        vm.prank(buyer);
        escrow.deposit(ORDER_ID);

        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: invalid state");
        escrow.deposit(ORDER_ID);
    }

    function test_Revert_NonBuyerDeposit() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);

        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: only buyer");
        escrow.deposit(ORDER_ID);
    }

    function test_Revert_NonSellerConfirm() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID);

        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: only seller");
        escrow.confirmDelivery(ORDER_ID);
    }

    function test_Revert_NonBuyerRelease() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID);
        vm.prank(seller);
        escrow.confirmDelivery(ORDER_ID);

        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: only buyer");
        escrow.releasePayment(ORDER_ID);
    }

    // ─── Cancel ───

    function test_CancelOrderInCreated() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);

        vm.prank(buyer);
        bool cancelled = escrow.cancelOrder(ORDER_ID);
        assertTrue(cancelled);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.CANCELLED));
    }

    function test_Revert_CancelAfterDeposit() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID);

        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: invalid state");
        escrow.cancelOrder(ORDER_ID);
    }

    // ─── Refund ───

    function test_RefundFundedOrder() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID);

        // Buyer can refund FUNDED order without timeout
        vm.prank(buyer);
        bool refunded = escrow.refund(ORDER_ID);
        assertTrue(refunded);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.REFUNDED));

        // USDC returned to buyer
        assertEq(usdc.balanceOf(buyer), AMOUNT * 10);
    }

    function test_Revert_EarlyRefundInDelivered() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID);
        vm.prank(seller);
        escrow.confirmDelivery(ORDER_ID);

        // Refund should fail before delivery timeout
        vm.warp(block.timestamp + 1 hours);
        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: delivery timeout not yet reached");
        escrow.refund(ORDER_ID);
    }

    function test_RefundAfterDeliveryTimeout() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID);
        vm.prank(seller);
        escrow.confirmDelivery(ORDER_ID);

        // Warp past delivery timeout
        vm.warp(block.timestamp + 7 hours);

        // Anyone can trigger refund after timeout
        vm.prank(address(0x999));
        bool refunded = escrow.refund(ORDER_ID);
        assertTrue(refunded);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.REFUNDED));
    }

    // ─── Self-Order Protection ───

    function test_Revert_SelfOrder() public {
        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: cannot self-order");
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
    }

    // ─── Fee Withdrawal ───

    function test_OwnerWithdrawsFees() public {
        // Complete a full escrow flow
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID);
        vm.prank(seller);
        escrow.confirmDelivery(ORDER_ID);
        vm.prank(buyer);
        escrow.releasePayment(ORDER_ID);

        uint256 fees = escrow.accumulatedFees();
        assertEq(fees, 500_000);

        vm.prank(owner);
        escrow.withdrawFees(owner);
        assertEq(escrow.accumulatedFees(), 0);
        assertEq(usdc.balanceOf(owner), 500_000);
    }

    function test_Revert_NonOwnerFeeWithdrawal() public {
        vm.prank(buyer);
        vm.expectRevert();
        escrow.withdrawFees(buyer);
    }

    // ─── Fuzz ───

    function testFuzz_ValidOrderFlow(uint256 amount) public {
        vm.assume(amount > 2_000 && amount <= 10_000_000_000); // Must cover Tier 1 flat fee

        // Mint enough USDC to buyer
        usdc.mint(buyer, amount);
        vm.prank(buyer);
        usdc.approve(address(escrow), amount);

        // Create and fund
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, amount, 0, 0);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID);
        vm.prank(seller);
        escrow.confirmDelivery(ORDER_ID);
        vm.prank(buyer);
        escrow.releasePayment(ORDER_ID);

        // Verify amounts
        uint256 fee = escrow.calculateFee(amount);
        uint256 sellerAmount = amount - fee;

        assertEq(usdc.balanceOf(seller), sellerAmount);
        assertEq(escrow.accumulatedFees(), fee);
    }

    // ─── Tiered Fee Tests ───

    function test_Tier1_FlatFee_Micro() public {
        // Tier 1: ≤ 100_000 (≤ $0.10) → flat $0.002 fee
        uint256 microAmount = 50_000;
        bytes32 tid = keccak256("tier1-test");

        usdc.mint(buyer, microAmount);
        vm.prank(buyer);
        usdc.approve(address(escrow), microAmount);

        vm.prank(buyer);
        escrow.createOrder(tid, seller, microAmount, 0, 0);
        vm.prank(buyer);
        escrow.deposit(tid);
        vm.prank(seller);
        escrow.confirmDelivery(tid);
        vm.prank(buyer);
        escrow.releasePayment(tid);

        // Fee should be flat $0.002 (2_000), not 0.5%
        assertEq(escrow.accumulatedFees(), 2_000);
        assertEq(usdc.balanceOf(seller), microAmount - 2_000);
    }

    function test_Tier1_FlatFee_MaxBoundary() public {
        // Boundary: exactly $0.10 → flat fee
        uint256 boundaryAmount = 100_000;
        bytes32 tid = keccak256("tier1-boundary");

        usdc.mint(buyer, boundaryAmount);
        vm.prank(buyer);
        usdc.approve(address(escrow), boundaryAmount);

        vm.prank(buyer);
        escrow.createOrder(tid, seller, boundaryAmount, 0, 0);
        vm.prank(buyer);
        escrow.deposit(tid);
        vm.prank(seller);
        escrow.confirmDelivery(tid);
        vm.prank(buyer);
        escrow.releasePayment(tid);

        assertEq(escrow.accumulatedFees(), 2_000);
    }

    function test_Tier2_PercentageFee() public {
        // Tier 2: $0.10-$1.00 → 1%
        uint256 mediumAmount = 500_000; // $0.50
        bytes32 tid = keccak256("tier2-test");

        usdc.mint(buyer, mediumAmount);
        vm.prank(buyer);
        usdc.approve(address(escrow), mediumAmount);

        vm.prank(buyer);
        escrow.createOrder(tid, seller, mediumAmount, 0, 0);
        vm.prank(buyer);
        escrow.deposit(tid);
        vm.prank(seller);
        escrow.confirmDelivery(tid);
        vm.prank(buyer);
        escrow.releasePayment(tid);

        // 1% of 500_000 = 5_000
        assertEq(escrow.accumulatedFees(), 500_000 / 100);
        assertEq(usdc.balanceOf(seller), mediumAmount - 5_000);
    }

    function test_Tier2_PercentageFee_MaxBoundary() public {
        // Boundary: exactly $1.00 → 1%
        uint256 boundaryAmount = 1_000_000;
        bytes32 tid = keccak256("tier2-boundary");

        usdc.mint(buyer, boundaryAmount);
        vm.prank(buyer);
        usdc.approve(address(escrow), boundaryAmount);

        vm.prank(buyer);
        escrow.createOrder(tid, seller, boundaryAmount, 0, 0);
        vm.prank(buyer);
        escrow.deposit(tid);
        vm.prank(seller);
        escrow.confirmDelivery(tid);
        vm.prank(buyer);
        escrow.releasePayment(tid);

        assertEq(escrow.accumulatedFees(), 10_000); // 1% of 1_000_000
    }

    function test_Tier3_PercentageFee() public {
        // Tier 3: > $1.00 → 0.5% (same as previous flat fee for standard amounts)
        uint256 standardAmount = 10_000_000; // $10.00
        bytes32 tid = keccak256("tier3-test");

        usdc.mint(buyer, standardAmount);
        vm.prank(buyer);
        usdc.approve(address(escrow), standardAmount);

        vm.prank(buyer);
        escrow.createOrder(tid, seller, standardAmount, 0, 0);
        vm.prank(buyer);
        escrow.deposit(tid);
        vm.prank(seller);
        escrow.confirmDelivery(tid);
        vm.prank(buyer);
        escrow.releasePayment(tid);

        // 0.5% of 10_000_000 = 50_000
        assertEq(escrow.accumulatedFees(), 50_000);
    }

    function test_CalculateFee_Unit() public {
        // Unit test calculateFee directly
        assertEq(escrow.calculateFee(1), 2_000);          // Tier 1: flat fee dominates
        assertEq(escrow.calculateFee(100_000), 2_000);     // Tier 1 boundary
        assertEq(escrow.calculateFee(100_001), 1_000);     // Tier 2: 1% of 100_001 = 1_000
        assertEq(escrow.calculateFee(1_000_000), 10_000);  // Tier 2 boundary
        assertEq(escrow.calculateFee(1_000_001), 5_000);   // Tier 3: 0.5% of 1_000_001 = 5_000
        assertEq(escrow.calculateFee(100_000_000), 500_000); // Tier 3: 0.5% of 100 USDC
    }

    // ─── x402 Bridge Tests ───

    function test_X402_HappyPath() public {
        // Buyer initiates escrow from an x402 payment
        uint256 x402Amount = 50_000_000; // 50 USDC
        usdc.mint(buyer, x402Amount);

        vm.prank(buyer);
        bytes32 orderId = escrow.initiateFromX402(seller, X402_TX_HASH, x402Amount);

        // Order should be in FUNDED state
        assertEq(uint8(escrow.getOrderState(orderId)), uint8(PaymentEscrow.OrderState.FUNDED));

        // Receipt should be marked as used
        assertTrue(escrow.usedX402Receipts(X402_TX_HASH));

        // x402 receipt should be linked
        assertEq(escrow.x402OrderReceipts(orderId), X402_TX_HASH);
    }

    function test_X402_FullEscrowFlow() public {
        uint256 x402Amount = 50_000_000;
        // x402 has already transferred USDC to the escrow contract
        usdc.mint(address(escrow), x402Amount);

        vm.prank(buyer);
        bytes32 orderId = escrow.initiateFromX402(seller, X402_TX_HASH, x402Amount);

        // 1. Seller confirms delivery
        vm.prank(seller);
        escrow.confirmDelivery(orderId);

        // 2. Buyer releases payment
        vm.prank(buyer);
        escrow.releasePayment(orderId);

        assertEq(uint8(escrow.getOrderState(orderId)), uint8(PaymentEscrow.OrderState.COMPLETED));

        // Verify fee (Tier 3: 0.5%)
        assertEq(escrow.accumulatedFees(), 250_000);
        assertEq(usdc.balanceOf(seller), x402Amount - 250_000);
    }

    function test_Revert_X402_DuplicateReceipt() public {
        vm.prank(buyer);
        escrow.initiateFromX402(seller, X402_TX_HASH, 50_000_000);

        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: x402 receipt already used");
        escrow.initiateFromX402(seller, X402_TX_HASH, 50_000_000);
    }

    function test_Revert_X402_ZeroAmount() public {
        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: amount must be > 0");
        escrow.initiateFromX402(seller, X402_TX_HASH, 0);
    }

    function test_Revert_X402_ZeroHash() public {
        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: invalid x402 hash");
        escrow.initiateFromX402(seller, bytes32(0), 50_000_000);
    }

    function test_Revert_X402_SelfOrder() public {
        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: cannot self-order");
        escrow.initiateFromX402(seller, X402_TX_HASH, 50_000_000);
    }
}
