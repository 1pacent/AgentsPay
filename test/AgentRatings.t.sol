// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {AgentRatings} from "../src/AgentRatings.sol";

contract AgentRatingsTest is Test {
    AgentRatings public ratings;

    address public buyer1     = address(0x101);
    address public buyer2     = address(0x102);
    address public seller1    = address(0x201);
    address public seller2    = address(0x202);

    string constant EMPTY_CID = "";

    // Valid 5-star rating
    uint8 constant Q5 = 5;
    uint8 constant A5 = 5;
    uint8 constant S5 = 5;
    uint8 constant C5 = 5;
    uint8 constant H5 = 5;

    // Mid rating
    uint8 constant Q3 = 3;
    uint8 constant A3 = 3;
    uint8 constant S3 = 3;
    uint8 constant C3 = 3;
    uint8 constant H3 = 3;

    // Poor rating
    uint8 constant Q1 = 1;
    uint8 constant A1 = 1;
    uint8 constant S1 = 1;
    uint8 constant C1 = 1;
    uint8 constant H1 = 1;

    function setUp() public {
        ratings = new AgentRatings();
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // submitRating — valid submissions
    // ════════════════════════════════════════════════════════════════════════════════

    function test_submitRating_valid5Star() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        (uint256 avg, uint256 total) = ratings.getAverageScore(seller1);
        assertEq(total, 1, "Should have 1 rating");
        assertEq(avg, 5, "5-star all dims = composite 5");
    }

    function test_submitRating_validMidRating() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q3, A3, S3, C3, H3, EMPTY_CID);

        (uint256 avg, uint256 total) = ratings.getAverageScore(seller1);
        assertEq(total, 1);
        // Composite = (3*30 + 3*25 + 3*15 + 3*15 + 3*15) / 100 = 300/100 = 3
        assertEq(avg, 3);
    }

    function test_submitRating_mixedDimensions() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, 5, 4, 3, 2, 1, EMPTY_CID);

        (uint256 avg,) = ratings.getAverageScore(seller1);
        // Composite = (5*30 + 4*25 + 3*15 + 2*15 + 1*15) / 100
        //           = (150 + 100 + 45 + 30 + 15) / 100
        //           = 340 / 100 = 3
        assertEq(avg, 3);
    }

    function test_submitRating_multipleBuyersOneSeller() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        vm.prank(buyer2);
        ratings.submitRating(seller1, 2, Q3, A3, S3, C3, H3, EMPTY_CID);

        (uint256 avg, uint256 total) = ratings.getAverageScore(seller1);
        assertEq(total, 2);
        // Avg = (5 + 3) / 2 = 4
        assertEq(avg, 4);
    }

    function test_submitRating_multipleSellers() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        vm.prank(buyer1);
        ratings.submitRating(seller2, 2, Q1, A1, S1, C1, H1, EMPTY_CID);

        (uint256 avg1,) = ratings.getAverageScore(seller1);
        assertEq(avg1, 5, "Seller1 should have 5");

        (uint256 avg2,) = ratings.getAverageScore(seller2);
        assertEq(avg2, 1, "Seller2 should have 1");
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // submitRating — duplicate rejection
    // ════════════════════════════════════════════════════════════════════════════════

    function test_submitRating_duplicateOrderRejected() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        vm.prank(buyer1);
        vm.expectRevert("Already rated");
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);
    }

    function test_submitRating_sameBuyerDifferentOrderAllowed() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        vm.prank(buyer1);
        ratings.submitRating(seller1, 2, Q3, A3, S3, C3, H3, EMPTY_CID);

        (uint256 avg, uint256 total) = ratings.getAverageScore(seller1);
        assertEq(total, 2, "Two different orders should both be counted");
        assertEq(avg, 4, "Avg of 5 and 3 = 4");
    }

    function test_submitRating_differentBuyerSameOrderAllowed() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 42, Q5, A5, S5, C5, H5, EMPTY_CID);

        // Buyer 2 can rate the same orderId because key includes buyer address
        vm.prank(buyer2);
        ratings.submitRating(seller1, 42, Q3, A3, S3, C3, H3, EMPTY_CID);

        (uint256 avg, uint256 total) = ratings.getAverageScore(seller1);
        assertEq(total, 2);
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // submitRating — out-of-range values rejected
    // ════════════════════════════════════════════════════════════════════════════════

    function test_submitRating_qualityZeroReverts() public {
        vm.prank(buyer1);
        vm.expectRevert("Quality range");
        ratings.submitRating(seller1, 1, 0, A5, S5, C5, H5, EMPTY_CID);
    }

    function test_submitRating_qualitySixReverts() public {
        vm.prank(buyer1);
        vm.expectRevert("Quality range");
        ratings.submitRating(seller1, 1, 6, A5, S5, C5, H5, EMPTY_CID);
    }

    function test_submitRating_accuracyZeroReverts() public {
        vm.prank(buyer1);
        vm.expectRevert("Accuracy range");
        ratings.submitRating(seller1, 1, Q5, 0, S5, C5, H5, EMPTY_CID);
    }

    function test_submitRating_speedZeroReverts() public {
        vm.prank(buyer1);
        vm.expectRevert("Speed range");
        ratings.submitRating(seller1, 1, Q5, A5, 0, C5, H5, EMPTY_CID);
    }

    function test_submitRating_commZeroReverts() public {
        vm.prank(buyer1);
        vm.expectRevert("Comm range");
        ratings.submitRating(seller1, 1, Q5, A5, S5, 0, H5, EMPTY_CID);
    }

    function test_submitRating_hireZeroReverts() public {
        vm.prank(buyer1);
        vm.expectRevert("Hire range");
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, 0, EMPTY_CID);
    }

    function test_submitRating_allDimensionsSixReverts() public {
        vm.prank(buyer1);
        // First dimension validated (quality) catches the 6
        vm.expectRevert("Quality range");
        ratings.submitRating(seller1, 1, 6, 6, 6, 6, 6, EMPTY_CID);
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // getAverageScore
    // ════════════════════════════════════════════════════════════════════════════════

    function test_getAverageScore_noRatingsReturnsZero() public {
        (uint256 avg, uint256 total) = ratings.getAverageScore(seller1);
        assertEq(avg, 0);
        assertEq(total, 0);
    }

    function test_getAverageScore_correctAfterMultipleRatings() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        vm.prank(buyer2);
        ratings.submitRating(seller1, 2, Q1, A1, S1, C1, H1, EMPTY_CID);

        (uint256 avg, uint256 total) = ratings.getAverageScore(seller1);
        assertEq(total, 2);
        // Composite of 5-star = (5*100)/100 = 5
        // Composite of 1-star = (1*100)/100 = 1
        // Avg = (5 + 1) / 2 = 3
        assertEq(avg, 3);
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // getBreakdown
    // ════════════════════════════════════════════════════════════════════════════════

    function test_getBreakdown_noRatingsReturnsZeros() public {
        (
            uint256 total, uint256 avgC, uint256 avgQ,
            uint256 avgA, uint256 avgS, uint256 avgComm, uint256 avgH
        ) = ratings.getBreakdown(seller1);

        assertEq(total, 0);
        assertEq(avgC, 0);
        assertEq(avgQ, 0);
        assertEq(avgA, 0);
        assertEq(avgS, 0);
        assertEq(avgComm, 0);
        assertEq(avgH, 0);
    }

    function test_getBreakdown_perDimensionCorrect() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, 5, 4, 3, 2, 1, EMPTY_CID);

        (
            uint256 total, uint256 avgC, uint256 avgQ,
            uint256 avgA, uint256 avgS, uint256 avgComm, uint256 avgH
        ) = ratings.getBreakdown(seller1);

        assertEq(total, 1);
        assertEq(avgQ, 5);
        assertEq(avgA, 4);
        assertEq(avgS, 3);
        assertEq(avgComm, 2);
        assertEq(avgH, 1);
        // Composite = (5*30 + 4*25 + 3*15 + 2*15 + 1*15)/100 = 340/100 = 3
        assertEq(avgC, 3);
    }

    function test_getBreakdown_twoRatingsAverages() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, 5, 5, 5, 5, 5, EMPTY_CID);

        vm.prank(buyer2);
        ratings.submitRating(seller1, 2, 1, 1, 1, 1, 1, EMPTY_CID);

        (
            uint256 total, uint256 avgC, uint256 avgQ,
            uint256 avgA, uint256 avgS, uint256 avgComm, uint256 avgH
        ) = ratings.getBreakdown(seller1);

        assertEq(total, 2);
        assertEq(avgQ, 3);         // (5+1)/2
        assertEq(avgA, 3);
        assertEq(avgS, 3);
        assertEq(avgComm, 3);
        assertEq(avgH, 3);
        // Composite average = (compositeSum=5+1) / 2 = 3
        assertEq(avgC, 3);
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // buyerRatingCount — increments per submission
    // ════════════════════════════════════════════════════════════════════════════════

    function test_buyerRatingCount_increments() public {
        assertEq(ratings.buyerRatingCount(buyer1), 0);

        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        assertEq(ratings.buyerRatingCount(buyer1), 1);

        vm.prank(buyer1);
        ratings.submitRating(seller2, 2, Q3, A3, S3, C3, H3, EMPTY_CID);

        assertEq(ratings.buyerRatingCount(buyer1), 2);
    }

    function test_buyerRatingCount_separatePerBuyer() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        vm.prank(buyer2);
        ratings.submitRating(seller1, 2, Q3, A3, S3, C3, H3, EMPTY_CID);

        assertEq(ratings.buyerRatingCount(buyer1), 1);
        assertEq(ratings.buyerRatingCount(buyer2), 1);
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // Buyer tier queries
    // ════════════════════════════════════════════════════════════════════════════════

    function test_getBuyerTier_noneWhenZero() public {
        assertEq(uint256(ratings.getBuyerTier(buyer1)), uint256(AgentRatings.BuyerTier.NONE));
    }

    function test_getBuyerTier_bronzeAt5() public {
        _rateAsBuyer(buyer1, 5, 1);  // 5 ratings, starting at orderId 1
        assertEq(uint256(ratings.getBuyerTier(buyer1)), uint256(AgentRatings.BuyerTier.BRONZE));
    }

    function test_getBuyerTier_silverAt25() public {
        _rateAsBuyer(buyer1, 25, 1);
        assertEq(uint256(ratings.getBuyerTier(buyer1)), uint256(AgentRatings.BuyerTier.SILVER));
    }

    function test_getBuyerTier_goldAt100() public {
        _rateAsBuyer(buyer1, 100, 1);
        assertEq(uint256(ratings.getBuyerTier(buyer1)), uint256(AgentRatings.BuyerTier.GOLD));
    }

    function test_getBuyerTier_platinumAt500() public {
        _rateAsBuyer(buyer1, 500, 1);
        assertEq(uint256(ratings.getBuyerTier(buyer1)), uint256(AgentRatings.BuyerTier.PLATINUM));
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // Edge cases
    // ════════════════════════════════════════════════════════════════════════════════

    function test_submitRating_withCommentCid() public {
        string memory cid = "ipfs://QmTest123";
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, cid);
    }

    function test_submitRating_doesNotCountForSellerRatingCount() public {
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        assertEq(ratings.buyerRatingCount(seller1), 0, "Seller should not get buyer count");
        assertEq(ratings.buyerRatingCount(buyer1), 1, "Buyer should get count");
    }

    function test_lastRatingTime_updated() public {
        vm.warp(1_000_000);
        vm.prank(buyer1);
        ratings.submitRating(seller1, 1, Q5, A5, S5, C5, H5, EMPTY_CID);

        (,,,,,,, uint256 lastTime) = ratings.agentRatings(seller1);
        assertEq(lastTime, 1_000_000);
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // tierThreshold helper
    // ════════════════════════════════════════════════════════════════════════════════

    function test_tierThreshold() public {
        assertEq(ratings.tierThreshold(AgentRatings.BuyerTier.NONE), 0);
        assertEq(ratings.tierThreshold(AgentRatings.BuyerTier.BRONZE), 5);
        assertEq(ratings.tierThreshold(AgentRatings.BuyerTier.SILVER), 25);
        assertEq(ratings.tierThreshold(AgentRatings.BuyerTier.GOLD), 100);
        assertEq(ratings.tierThreshold(AgentRatings.BuyerTier.PLATINUM), 500);
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // Helpers
    // ════════════════════════════════════════════════════════════════════════════════

    function _rateAsBuyer(address buyer, uint256 count, uint256 startOrderId) internal {
        for (uint256 i = 0; i < count; i++) {
            address seller = (i % 2 == 0) ? seller1 : seller2;
            vm.prank(buyer);
            ratings.submitRating(seller, startOrderId + i, Q3, A3, S3, C3, H3, EMPTY_CID);
        }
    }
}