// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/AgentRegistry.sol";

contract AgentRegistryTest is Test {
    AgentRegistry public registry;

    address public owner = address(0x100);
    address public agent = address(0x200);
    address public buyer = address(0x300);

    string constant AGENT_ID = "agent-alpha-001";
    string constant CAPABILITY = "data_processing";

    function setUp() public {
        vm.prank(owner);
        registry = new AgentRegistry();
    }

    // ─── Register ───

    function test_RegisterAgent() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        bool success = registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);
        assertTrue(success);

        AgentRegistry.AgentInfo memory info = registry.getAgent(AGENT_ID);
        assertEq(info.agentId, AGENT_ID);
        assertEq(info.payoutWallet, agent);
        assertTrue(info.active);
    }

    function test_Revert_DuplicateAgent() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);

        vm.prank(owner);
        vm.expectRevert("AgentRegistry: agent already registered");
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);
    }

    function test_Revert_ZeroPayoutWallet() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        vm.expectRevert("AgentRegistry: invalid payout wallet");
        registry.registerAgent(AGENT_ID, caps, address(0), 0, 1e6);
    }

    function test_Revert_EmptyCapabilities() public {
        string[] memory caps = new string[](0);

        vm.prank(owner);
        vm.expectRevert("AgentRegistry: at least one capability required");
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);
    }

    // ─── Update ───

    function test_UpdateRegistration() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);

        string[] memory newCaps = new string[](2);
        newCaps[0] = CAPABILITY;
        newCaps[1] = "code_review";

        vm.prank(owner);
        bool success = registry.updateRegistration(AGENT_ID, newCaps, agent, 5e5, 2e6);
        assertTrue(success);
    }

    // ─── Deregister ───

    function test_DeregisterAgent() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);

        vm.prank(owner);
        bool success = registry.deregisterAgent(AGENT_ID);
        assertTrue(success);
    }

    function test_Deregister_ExcludedFromDiscover() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);

        vm.prank(owner);
        registry.deregisterAgent(AGENT_ID);

        AgentRegistry.AgentInfo[] memory results = registry.discover(CAPABILITY);
        assertEq(results.length, 0);
    }

    // ─── Discover ───

    function test_DiscoverByCapability() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);

        AgentRegistry.AgentInfo[] memory results = registry.discover(CAPABILITY);
        assertEq(results.length, 1);
        assertEq(results[0].agentId, AGENT_ID);
    }

    function test_Discover_ReturnsEmptyForUnknownCapability() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);

        AgentRegistry.AgentInfo[] memory results = registry.discover("image_generation");
        assertEq(results.length, 0);
    }

    // ─── Reputation ───

    function test_ReputationScoring() public {
        string[] memory caps = new string[](1);
        caps[0] = CAPABILITY;

        vm.prank(owner);
        registry.registerAgent(AGENT_ID, caps, agent, 0, 1e6);

        vm.prank(owner);
        uint256 score = registry.updateReputation(AGENT_ID, 3, 2);

        // 2/3 = 6666 / 10000
        assertEq(score, 6666);
    }

    // ─── Fuzz ───

    function testFuzz_RegisterValidAgent(string memory agentId) public {
        vm.assume(bytes(agentId).length > 0 && bytes(agentId).length < 64);

        string[] memory caps = new string[](1);
        caps[0] = "fuzz_test";

        vm.prank(owner);
        bool success = registry.registerAgent(agentId, caps, agent, 0, 1e6);
        assertTrue(success);
    }
}
