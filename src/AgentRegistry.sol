// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title AgentRegistry
 * @notice On-chain registry for agent capabilities, pricing, and reputation
 * @dev Part of the AgentPays protocol — agents register with capabilities and wallet
 */
contract AgentRegistry is Ownable, ReentrancyGuard {

    // ──────────────────────────────────────────────
    // Types
    // ──────────────────────────────────────────────

    struct AgentInfo {
        string agentId;
        string[] capabilities;
        address payoutWallet;
        uint256 minPrice;       // Minimum price per call (USDC, 6 decimals)
        uint256 maxPrice;       // Maximum price per call (USDC, 6 decimals)
        uint256 trustScore;     // Reputation score (0–10000, where 10000 = 100%)
        uint256 totalJobs;
        uint256 successfulJobs;
        bool active;
        uint256 registeredAt;
    }

    // ──────────────────────────────────────────────
    // State
    // ──────────────────────────────────────────────

    mapping(string => AgentInfo) private agents;
    string[] private agentIds;

    // ──────────────────────────────────────────────
    // Events
    // ──────────────────────────────────────────────

    event AgentRegistered(
        string indexed agentId,
        address indexed payoutWallet,
        string[] capabilities,
        uint256 minPrice,
        uint256 maxPrice
    );

    event AgentUpdated(
        string indexed agentId,
        address indexed payoutWallet,
        string[] capabilities,
        uint256 minPrice,
        uint256 maxPrice
    );

    event AgentDeregistered(string indexed agentId);
    event ReputationUpdated(string indexed agentId, uint256 newScore, uint256 totalJobs, uint256 successfulJobs);

    // ──────────────────────────────────────────────
    // Constructor
    // ──────────────────────────────────────────────

    constructor() Ownable(msg.sender) {}

    // ──────────────────────────────────────────────
    // Registration
    // ──────────────────────────────────────────────

    function registerAgent(
        string calldata agentId,
        string[] memory capabilities,
        address payoutWallet,
        uint256 minPrice,
        uint256 maxPrice
    ) external nonReentrant returns (bool) {
        require(bytes(agentId).length > 0, "AgentRegistry: agentId cannot be empty");
        require(payoutWallet != address(0), "AgentRegistry: invalid payout wallet");
        require(maxPrice >= minPrice, "AgentRegistry: maxPrice must be >= minPrice");
        require(!agents[agentId].active, "AgentRegistry: agent already registered");
        require(capabilities.length > 0, "AgentRegistry: at least one capability required");

        agents[agentId] = AgentInfo({
            agentId: agentId,
            capabilities: capabilities,
            payoutWallet: payoutWallet,
            minPrice: minPrice,
            maxPrice: maxPrice,
            trustScore: 0,
            totalJobs: 0,
            successfulJobs: 0,
            active: true,
            registeredAt: block.timestamp
        });

        agentIds.push(agentId);

        emit AgentRegistered(agentId, payoutWallet, capabilities, minPrice, maxPrice);
        return true;
    }

    function updateRegistration(
        string calldata agentId,
        string[] memory capabilities,
        address payoutWallet,
        uint256 minPrice,
        uint256 maxPrice
    ) external nonReentrant returns (bool) {
        require(agents[agentId].active, "AgentRegistry: agent not active");
        require(payoutWallet != address(0), "AgentRegistry: invalid payout wallet");
        require(maxPrice >= minPrice, "AgentRegistry: maxPrice must be >= minPrice");

        AgentInfo storage agent = agents[agentId];
        agent.capabilities = capabilities;
        agent.payoutWallet = payoutWallet;
        agent.minPrice = minPrice;
        agent.maxPrice = maxPrice;

        emit AgentUpdated(agentId, payoutWallet, capabilities, minPrice, maxPrice);
        return true;
    }

    function deregisterAgent(string calldata agentId) external nonReentrant returns (bool) {
        require(agents[agentId].active, "AgentRegistry: agent not active");

        agents[agentId].active = false;

        emit AgentDeregistered(agentId);
        return true;
    }

    // ──────────────────────────────────────────────
    // Queries
    // ──────────────────────────────────────────────

    function getAgent(string calldata agentId) external view returns (AgentInfo memory) {
        require(agents[agentId].active, "AgentRegistry: agent not found");
        return agents[agentId];
    }

    function discover(string calldata capabilityCategory) external view returns (AgentInfo[] memory) {
        uint256 count;

        // First pass: count matching agents
        for (uint256 i = 0; i < agentIds.length; i++) {
            AgentInfo storage agent = agents[agentIds[i]];
            if (!agent.active) continue;

            for (uint256 j = 0; j < agent.capabilities.length; j++) {
                if (keccak256(bytes(agent.capabilities[j])) == keccak256(bytes(capabilityCategory))) {
                    count++;
                    break;
                }
            }
        }

        // Second pass: populate
        AgentInfo[] memory result = new AgentInfo[](count);
        uint256 idx;

        for (uint256 i = 0; i < agentIds.length; i++) {
            AgentInfo storage agent = agents[agentIds[i]];
            if (!agent.active) continue;

            for (uint256 j = 0; j < agent.capabilities.length; j++) {
                if (keccak256(bytes(agent.capabilities[j])) == keccak256(bytes(capabilityCategory))) {
                    result[idx] = agent;
                    idx++;
                    break;
                }
            }
        }

        return result;
    }

    function getAgentCount() external view returns (uint256) {
        return agentIds.length;
    }

    function getActiveAgentCount() external view returns (uint256) {
        uint256 count;
        for (uint256 i = 0; i < agentIds.length; i++) {
            if (agents[agentIds[i]].active) count++;
        }
        return count;
    }

    // ──────────────────────────────────────────────
    // Admin: Reputation
    // ──────────────────────────────────────────────

    function updateReputation(
        string calldata agentId,
        uint256 totalJobs,
        uint256 successfulJobs
    ) external onlyOwner nonReentrant returns (uint256) {
        require(agents[agentId].active, "AgentRegistry: agent not active");

        agents[agentId].totalJobs = totalJobs;
        agents[agentId].successfulJobs = successfulJobs;

        if (totalJobs > 0) {
            agents[agentId].trustScore = (successfulJobs * 10000) / totalJobs;
        }

        emit ReputationUpdated(agentId, agents[agentId].trustScore, totalJobs, successfulJobs);
        return agents[agentId].trustScore;
    }

    // ──────────────────────────────────────────────
    // Admin: Emergency
    // ──────────────────────────────────────────────

    function emergencyDeregister(string calldata agentId) external onlyOwner nonReentrant {
        require(agents[agentId].active, "AgentRegistry: agent not active");
        agents[agentId].active = false;
        emit AgentDeregistered(agentId);
    }
}
