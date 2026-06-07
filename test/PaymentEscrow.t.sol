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
        assertEq(escrow.getOrderState(ORDER_ID), PaymentEscrow.OrderState.FUNDED);

        // 3. Seller confirms delivery
        vm.prank(seller);
        bool confirmed = escrow.confirmDelivery(ORDER_ID);
        assertTrue(confirmed);
        assertEq(escrow.getOrderState(ORDER_ID), PaymentEscrow.OrderState.DELIVERED);

        // 4. Buyer releases payment
        vm.prank(buyer);
        bool released = escrow.releasePayment(ORDER_ID);
        assertTrue(released);
        assertEq(escrow.getOrderState(ORDER_ID), PaymentEscrow.OrderState.COMPLETED);

        // Check seller received 99.5 USDC (99_500_000)
        assertEq(usdc.balanceOf(seller), 99_500_000);

        // Check fees accumulated (0.5 USDC = 500_000)
        assertEq(escrow.accumulatedFees(), 500_000);
    }

    // ─── State Machine ───

    function test_Revert_DepositBeforeCreate() public {
        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: invalid state");
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
        assertEq(escrow.getOrderState(ORDER_ID), PaymentEscrow.OrderState.CANCELLED);
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
        assertEq(escrow.getOrderState(ORDER_ID), PaymentEscrow.OrderState.REFUNDED);

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
        assertEq(escrow.getOrderState(ORDER_ID), PaymentEscrow.OrderState.REFUNDED);
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
        vm.assume(amount > 0 && amount <= 10_000_000_000);

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
        uint256 fee = (amount * 50) / 10000;
        uint256 sellerAmount = amount - fee;

        assertEq(usdc.balanceOf(seller), sellerAmount);
        assertEq(escrow.accumulatedFees(), fee);
    }
}
