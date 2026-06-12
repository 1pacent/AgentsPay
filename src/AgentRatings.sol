// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title AgentRatings
/// @notice 5-dimension weighted rating system for AgentPays agents on Base.
///         Composite score = weighted average of quality, accuracy, speed,
///         communication, and would-hire-again dimensions (each 1-5).
///         Buyer tier tracking by rating QUANTITY (not score) — prevents
///         score inflation incentives.
/// @dev Ratings MUST happen AFTER payment release (enforced by caller).
///      RATING_WINDOW constant is reserved for future PaymentEscrow
///      integration — currently a documentation constant only.
///      Buyer tiers (view-only):
///      - Bronze:   5+ ratings (badge)
///      - Silver:  25+ ratings (10% fee discount)
///      - Gold:    100+ ratings (25% fee discount)
///      - Platinum: 500+ ratings (100% fees waived)
contract AgentRatings {

    // ════════════════════════════════════════════════════════════════════════════════
    // Types
    // ════════════════════════════════════════════════════════════════════════════════

    struct RatingSummary {
        uint256 totalRatings;
        uint256 compositeSum;
        uint256 qualitySum;
        uint256 accuracySum;
        uint256 speedSum;
        uint256 communicationSum;
        uint256 wouldHireAgainSum;
        uint256 lastRatingTime;
    }

    enum BuyerTier {
        NONE,      // 0 ratings
        BRONZE,    // 5+ ratings
        SILVER,    // 25+ ratings
        GOLD,      // 100+ ratings
        PLATINUM   // 500+ ratings
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // State
    // ════════════════════════════════════════════════════════════════════════════════

    /// @dev agent address => rating summary
    mapping(address => RatingSummary) public agentRatings;

    /// @dev keccak256(buyer, orderId) => rated (prevents double-rating)
    mapping(bytes32 => bool) public orderRated;

    /// @dev buyer address => total rating count (for tier computation)
    mapping(address => uint256) public buyerRatingCount;

    // ════════════════════════════════════════════════════════════════════════════════
    // Constants
    // ════════════════════════════════════════════════════════════════════════════════

    /// @notice Time window after payment release during which a rating
    ///         can be submitted. RESERVED — not enforced on-chain in V1.
    ///         Enforced at the application layer (MCP server) pending
    ///         PaymentEscrow integration.
    uint256 public constant RATING_WINDOW = 48 hours;

    // Weights — sum to 100 for simple percentage math
    uint256 public constant WEIGHT_QUALITY       = 30;
    uint256 public constant WEIGHT_ACCURACY      = 25;
    uint256 public constant WEIGHT_SPEED         = 15;
    uint256 public constant WEIGHT_COMMUNICATION = 15;
    uint256 public constant WEIGHT_HIRE_AGAIN    = 15;

    // Tier thresholds (quantity, not score)
    uint256 public constant TIER_BRONZE   = 5;
    uint256 public constant TIER_SILVER   = 25;
    uint256 public constant TIER_GOLD     = 100;
    uint256 public constant TIER_PLATINUM = 500;

    // ════════════════════════════════════════════════════════════════════════════════
    // Events
    // ════════════════════════════════════════════════════════════════════════════════

    /// @notice Emitted when a rating is submitted
    /// @param buyer The rater (msg.sender)
    /// @param seller The agent being rated
    /// @param orderId The order this rating references
    /// @param composite Weighted composite score (1-5)
    /// @param quality Quality score (1-5)
    /// @param accuracy Accuracy score (1-5)
    /// @param speed Speed score (1-5)
    /// @param communication Communication score (1-5)
    /// @param wouldHireAgain Would-hire-again score (1-5)
    /// @param commentCid IPFS/off-chain reference for optional review text
    event RatingSubmitted(
        address indexed buyer,
        address indexed seller,
        uint256 indexed orderId,
        uint8  composite,
        uint8  quality,
        uint8  accuracy,
        uint8  speed,
        uint8  communication,
        uint8  wouldHireAgain,
        string commentCid
    );

    /// @notice Emitted when the RATING_WINDOW enforcement is activated
    ///         in a future upgrade
    event RatingWindowEnforcementActivated();

    // ════════════════════════════════════════════════════════════════════════════════
    // Write functions
    // ════════════════════════════════════════════════════════════════════════════════

    /// @notice Submit a 5-dimension rating for an agent
    /// @param seller Agent address being rated
    /// @param orderId Order identifier (must be unique per buyer-order pair)
    /// @param quality Rating 1-5
    /// @param accuracy Rating 1-5
    /// @param speed Rating 1-5
    /// @param communication Rating 1-5
    /// @param wouldHireAgain Rating 1-5
    /// @param commentCid IPFS CID or off-chain URI (can be empty string)
    /// @dev Caller must be the buyer. Precondition: payment has been released.
    ///      The application layer (MCP server) is responsible for enforcing
    ///      that ratings happen after payment and within RATING_WINDOW.
    ///      Duplicate ratings for the same (buyer, orderId) pair are rejected.
    function submitRating(
        address seller,
        uint256 orderId,
        uint8  quality,
        uint8  accuracy,
        uint8  speed,
        uint8  communication,
        uint8  wouldHireAgain,
        string calldata commentCid
    ) external {
        bytes32 key = keccak256(abi.encodePacked(msg.sender, orderId));
        require(!orderRated[key], "Already rated");

        _requireValidDimension(quality, "Quality");
        _requireValidDimension(accuracy, "Accuracy");
        _requireValidDimension(speed, "Speed");
        _requireValidDimension(communication, "Comm");
        _requireValidDimension(wouldHireAgain, "Hire");

        orderRated[key] = true;

        // Weighted composite: sum(dimension * weight) / 100
        // Since each dimension is 1-5 and weights sum to 100, composite is 1-5
        uint256 composite = (
            quality       * WEIGHT_QUALITY
            + accuracy    * WEIGHT_ACCURACY
            + speed       * WEIGHT_SPEED
            + communication * WEIGHT_COMMUNICATION
            + wouldHireAgain * WEIGHT_HIRE_AGAIN
        ) / 100;

        RatingSummary storage s = agentRatings[seller];
        s.totalRatings++;
        s.compositeSum       += composite;
        s.qualitySum         += quality;
        s.accuracySum        += accuracy;
        s.speedSum           += speed;
        s.communicationSum   += communication;
        s.wouldHireAgainSum  += wouldHireAgain;
        s.lastRatingTime      = block.timestamp;

        buyerRatingCount[msg.sender]++;

        emit RatingSubmitted(
            msg.sender,
            seller,
            orderId,
            uint8(composite),
            quality,
            accuracy,
            speed,
            communication,
            wouldHireAgain,
            commentCid
        );
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // View functions
    // ════════════════════════════════════════════════════════════════════════════════

    /// @notice Get composite average score and total rating count
    /// @param agent Address to query
    /// @return avgComposite Average weighted composite (0 if no ratings)
    /// @return totalRatings Number of ratings received
    function getAverageScore(address agent) external view returns (uint256 avgComposite, uint256 totalRatings) {
        RatingSummary storage s = agentRatings[agent];
        if (s.totalRatings == 0) return (0, 0);
        return (s.compositeSum / s.totalRatings, s.totalRatings);
    }

    /// @notice Get full per-dimension breakdown for an agent
    /// @param agent Address to query
    /// @return totalRatings Number of ratings
    /// @return avgComposite Average weighted composite score (1-5)
    /// @return avgQuality Average quality score (1-5)
    /// @return avgAccuracy Average accuracy score (1-5)
    /// @return avgSpeed Average speed score (1-5)
    /// @return avgCommunication Average communication score (1-5)
    /// @return avgHireAgain Average would-hire-again score (1-5)
    function getBreakdown(address agent) external view returns (
        uint256 totalRatings,
        uint256 avgComposite,
        uint256 avgQuality,
        uint256 avgAccuracy,
        uint256 avgSpeed,
        uint256 avgCommunication,
        uint256 avgHireAgain
    ) {
        RatingSummary storage s = agentRatings[agent];
        if (s.totalRatings == 0) return (0, 0, 0, 0, 0, 0, 0);
        return (
            s.totalRatings,
            s.compositeSum      / s.totalRatings,
            s.qualitySum        / s.totalRatings,
            s.accuracySum       / s.totalRatings,
            s.speedSum          / s.totalRatings,
            s.communicationSum  / s.totalRatings,
            s.wouldHireAgainSum / s.totalRatings
        );
    }

    /// @notice Get the buyer tier for a given address
    /// @param buyer Address to check
    /// @return tier The BuyerTier enum value
    function getBuyerTier(address buyer) external view returns (BuyerTier tier) {
        uint256 count = buyerRatingCount[buyer];
        if (count >= TIER_PLATINUM) return BuyerTier.PLATINUM;
        if (count >= TIER_GOLD)     return BuyerTier.GOLD;
        if (count >= TIER_SILVER)   return BuyerTier.SILVER;
        if (count >= TIER_BRONZE)   return BuyerTier.BRONZE;
        return BuyerTier.NONE;
    }

    /// @notice Get the minimum rating count needed for a tier
    /// @param tier The tier to query
    /// @return minRatings Minimum ratings required (0 for NONE)
    function tierThreshold(BuyerTier tier) external pure returns (uint256 minRatings) {
        if (tier == BuyerTier.PLATINUM) return TIER_PLATINUM;
        if (tier == BuyerTier.GOLD)     return TIER_GOLD;
        if (tier == BuyerTier.SILVER)   return TIER_SILVER;
        if (tier == BuyerTier.BRONZE)   return TIER_BRONZE;
        return 0;
    }

    // ════════════════════════════════════════════════════════════════════════════════
    // Internal helpers
    // ════════════════════════════════════════════════════════════════════════════════

    /// @dev Validate a single dimension is in [1, 5] range
    function _requireValidDimension(uint8 value, string memory dimName) private pure {
        require(value >= 1 && value <= 5, string.concat(dimName, " range"));
    }
}