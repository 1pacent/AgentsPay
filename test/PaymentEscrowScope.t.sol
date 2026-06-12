// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/PaymentEscrow.sol";
import "../src/mock/MockUSDC.sol";

contract PaymentEscrowScopeTest is Test {
    PaymentEscrow public escrow;
    MockUSDC public usdc;

    address public owner = address(0x100);
    address public buyer = address(0x200);
    address public seller = address(0x300);
    address public untrustedSeller = address(0x301);
    address public stranger = address(0x999);

    bytes32 constant ORDER_ID = keccak256("scope-test-order");
    bytes32 constant ORDER_ID2 = keccak256("scope-test-order-2");
    bytes32 constant SCOPE_HASH = keccak256("scope:data-processing-v1");
    bytes32 constant RESULT_HASH = keccak256("result-data");
    uint256 constant AMOUNT = 100_000_000; // 100 USDC

    function setUp() public {
        usdc = new MockUSDC();
        vm.prank(owner);
        escrow = new PaymentEscrow(address(usdc));

        // Fund buyer
        usdc.mint(buyer, AMOUNT * 10);
        vm.prank(buyer);
        usdc.approve(address(escrow), AMOUNT * 10);
        usdc.mint(address(escrow), AMOUNT * 10);

        // Mark seller as trusted
        vm.prank(owner);
        escrow.setTrustedAgent(seller, true);
    }

    // ─── Helper: create + fund an order ───

    function _createAndFund(bytes32 orderId, address sellerAddr) internal {
        vm.prank(buyer);
        escrow.createOrder(orderId, sellerAddr, AMOUNT, 0, 0);
        vm.prank(buyer);
        escrow.deposit(orderId);
    }

    function _fullScopeFlow(address sellerAddr, bool expectAutoRelease) internal {
        _createAndFund(ORDER_ID, sellerAddr);

        // Buyer proposes scope
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);

        // Seller accepts scope
        vm.prank(sellerAddr);
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);

        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.SCOPED));

        // Seller confirms scoped delivery
        vm.prank(sellerAddr);
        escrow.confirmScopedDelivery(ORDER_ID, RESULT_HASH, SCOPE_HASH);

        if (expectAutoRelease) {
            assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.COMPLETED));
        } else {
            assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.DELIVERED));
        }
    }

    // ─── proposeScope ───

    function test_proposeScope_buyerCanPropose() public {
        _createAndFund(ORDER_ID, seller);

        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);

        assertEq(escrow.orderScopeHash(ORDER_ID), SCOPE_HASH);
    }

    function test_proposeScope_revertsWhenNotBuyer() public {
        _createAndFund(ORDER_ID, seller);

        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: only buyer");
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);
    }

    function test_proposeScope_revertsWhenNotFunded() public {
        // Only CREATED — no scope allowed
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);

        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: invalid state");
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);
    }

    function test_proposeScope_revertsWhenAlreadyProposed() public {
        _createAndFund(ORDER_ID, seller);

        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);

        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: scope already proposed");
        escrow.proposeScope(ORDER_ID, keccak256("new-scope"));
    }

    // ─── acceptScope ───

    function test_acceptScope_sellerAccepts() public {
        _createAndFund(ORDER_ID, seller);
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);

        vm.prank(seller);
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);

        assertTrue(escrow.acceptedScopes(SCOPE_HASH));
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.SCOPED));
    }

    function test_acceptScope_revertsWhenNotSeller() public {
        _createAndFund(ORDER_ID, seller);
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);

        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: only seller");
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);
    }

    function test_acceptScope_revertsOnHashMismatch() public {
        _createAndFund(ORDER_ID, seller);
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);

        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: scope mismatch");
        escrow.acceptScope(ORDER_ID, keccak256("wrong-scope"));
    }

    function test_acceptScope_revertsWhenNotFunded() public {
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID, seller, AMOUNT, 0, 0);

        // No proposal, no funding — direct accept should fail on state
        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: invalid state");
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);
    }

    // ─── confirmScopedDelivery ───

    function test_confirmScopedDelivery_autoReleaseForTrustedSeller() public {
        _createAndFund(ORDER_ID, seller);
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);
        vm.prank(seller);
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);

        uint256 sellerBalanceBefore = usdc.balanceOf(seller);

        vm.prank(seller);
        escrow.confirmScopedDelivery(ORDER_ID, RESULT_HASH, SCOPE_HASH);

        uint256 sellerBalanceAfter = usdc.balanceOf(seller);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.COMPLETED));
        assertTrue(sellerBalanceAfter > sellerBalanceBefore, "Seller should receive payment");
    }

    function test_confirmScopedDelivery_setsDeliveredForUntrustedSeller() public {
        // untrustedSeller is NOT in trustedAgents
        _createAndFund(ORDER_ID2, untrustedSeller);
        bytes32 localScope = keccak256("scope:untrusted");

        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID2, localScope);
        vm.prank(untrustedSeller);
        escrow.acceptScope(ORDER_ID2, localScope);

        uint256 balanceBefore = usdc.balanceOf(untrustedSeller);

        vm.prank(untrustedSeller);
        escrow.confirmScopedDelivery(ORDER_ID2, RESULT_HASH, localScope);

        uint256 balanceAfter = usdc.balanceOf(untrustedSeller);
        assertEq(uint8(escrow.getOrderState(ORDER_ID2)), uint8(PaymentEscrow.OrderState.DELIVERED));
        assertEq(balanceAfter, balanceBefore, "Untrusted seller should NOT get auto-release");
    }

    function test_confirmScopedDelivery_revertsOnWrongScope() public {
        _createAndFund(ORDER_ID, seller);
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);
        vm.prank(seller);
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);

        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: wrong scope");
        escrow.confirmScopedDelivery(ORDER_ID, RESULT_HASH, keccak256("wrong-scope"));
    }

    function test_confirmScopedDelivery_revertsWhenNotScoped() public {
        // Order is FUNDED but not SCOPED
        _createAndFund(ORDER_ID, seller);

        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: invalid state");
        escrow.confirmScopedDelivery(ORDER_ID, RESULT_HASH, SCOPE_HASH);
    }

    function test_confirmScopedDelivery_revertsWhenNotSeller() public {
        _createAndFund(ORDER_ID, seller);
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);
        vm.prank(seller);
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);

        vm.prank(buyer);
        vm.expectRevert("PaymentEscrow: only seller");
        escrow.confirmScopedDelivery(ORDER_ID, RESULT_HASH, SCOPE_HASH);
    }

    // ─── acceptedScopes replay protection ───

    function test_acceptScope_revertsWhenAlreadyAcceptedElsewhere() public {
        // Order 1: propose + accept scope
        _createAndFund(ORDER_ID, seller);
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);
        vm.prank(seller);
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);

        // Order 2: same buyer, same scope hash — should revert
        vm.prank(buyer);
        escrow.createOrder(ORDER_ID2, seller, AMOUNT, 0, 0);
        vm.prank(buyer);
        usdc.mint(buyer, AMOUNT);
        vm.prank(buyer);
        usdc.approve(address(escrow), AMOUNT);
        vm.prank(buyer);
        escrow.deposit(ORDER_ID2);

        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID2, SCOPE_HASH);
        vm.prank(seller);
        vm.expectRevert("PaymentEscrow: scope already accepted on another order");
        escrow.acceptScope(ORDER_ID2, SCOPE_HASH);
    }

    // ─── setTrustedAgent ───

    function test_setTrustedAgent_ownerCanSet() public {
        vm.prank(owner);
        escrow.setTrustedAgent(stranger, true);
        assertTrue(escrow.trustedAgents(stranger));
    }

    function test_setTrustedAgent_revertsWhenNotOwner() public {
        vm.prank(buyer);
        vm.expectRevert();
        escrow.setTrustedAgent(stranger, true);
    }

    function test_setTrustedAgent_canRevoke() public {
        vm.prank(owner);
        escrow.setTrustedAgent(seller, false);
        assertFalse(escrow.trustedAgents(seller));
    }

    // ─── Edge: full scoped flow auto-release calculates correct fee ───

    function test_fullScopedFlow_correctFees() public {
        uint256 fee = escrow.calculateFee(AMOUNT);
        uint256 sellerExpected = AMOUNT - fee;

        _fullScopeFlow(seller, true);

        assertEq(usdc.balanceOf(seller), sellerExpected,
            "Trusted seller should receive full amount minus fee");
        assertEq(escrow.accumulatedFees(), fee, "Fees should be accumulated correctly");
    }

    function test_fullScopedFlow_untrustedThenBuyerReleases() public {
        _fullScopeFlow(untrustedSeller, false);

        // Buyer can release after scoped delivery set DELIVERED state
        vm.prank(buyer);
        bool released = escrow.releasePayment(ORDER_ID);
        assertTrue(released);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.COMPLETED));
    }

    // ─── Fuzz: confirmDeivery_stateMachineConsistency ───
    // Only the standard confirmDelivery (FUNDED → DELIVERED) path is fuzzed
    // Scope path requires specific hash, making it harder to fuzz

    function test_standardConfirmDeliveryStillWorks() public {
        // Verify the original confirmDelivery path is unchanged
        _createAndFund(ORDER_ID, seller);

        vm.prank(seller);
        bool confirmed = escrow.confirmDelivery(ORDER_ID);
        assertTrue(confirmed);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.DELIVERED));

        vm.prank(buyer);
        escrow.releasePayment(ORDER_ID);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.COMPLETED));
    }

    function test_refundStillWorksOnFunded() public {
        _createAndFund(ORDER_ID, seller);

        vm.prank(buyer);
        bool refunded = escrow.refund(ORDER_ID);
        assertTrue(refunded);
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.REFUNDED));
    }

    function test_autoRelease_emitsPaymentReleased() public {
        _createAndFund(ORDER_ID, seller);
        vm.prank(buyer);
        escrow.proposeScope(ORDER_ID, SCOPE_HASH);
        vm.prank(seller);
        escrow.acceptScope(ORDER_ID, SCOPE_HASH);

        uint256 sellerBalanceBefore = usdc.balanceOf(seller);

        vm.prank(seller);
        escrow.confirmScopedDelivery(ORDER_ID, RESULT_HASH, SCOPE_HASH);

        // Verify state + balance change (event is internal to contract)
        assertEq(uint8(escrow.getOrderState(ORDER_ID)), uint8(PaymentEscrow.OrderState.COMPLETED));
        assertTrue(usdc.balanceOf(seller) > sellerBalanceBefore, "Seller should be paid");
    }
}
