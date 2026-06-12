// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "../src/AgentRatings.sol";

/// @title DeployRatings
/// @notice Foundry script to deploy AgentRatings to Base Sepolia.
///         Usage: forge script script/DeployRatings.s.sol --rpc-url base_sepolia --broadcast
contract DeployRatings is Script {
    function run() external {
        uint256 deployerPrivateKey = vm.envUint("DEPLOYER_PRIVATE_KEY");

        vm.startBroadcast(deployerPrivateKey);

        AgentRatings ratings = new AgentRatings();

        vm.stopBroadcast();

        console.log("AgentRatings deployed at:", address(ratings));
    }
}