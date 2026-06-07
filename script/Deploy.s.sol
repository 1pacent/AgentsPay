// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "../src/AgentRegistry.sol";
import "../src/PaymentEscrow.sol";
import "../src/mock/MockUSDC.sol";

/**
 * @title DeployAgentPays
 * @notice Deploys AgentPays contracts to Base Sepolia (or local testnet)
 * @dev Usage: forge script script/Deploy.s.sol --rpc-url base_sepolia --broadcast --verify -vvvv
 *
 * Environment variables:
 *   DEPLOYER_PRIVATE_KEY — Private key of the deployer
 *   BASE_SEPOLIA_RPC_URL — RPC endpoint for Base Sepolia
 *   BASESCAN_API_KEY     — Etherscan API key for contract verification
 *
 * Base Sepolia USDC (Circle Official): 0x036CbD53842c5426634e7929541eC2318f3dCF7e
 * Base Mainnet USDC: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
 */
contract DeployAgentPays is Script {
    // Base Sepolia official USDC address
    address constant BASE_SEPOLIA_USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;

    function run() external {
        uint256 deployerPrivateKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);

        console.log("Deploying AgentPays contracts...");
        console.log("Deployer:", deployer);

        vm.startBroadcast(deployerPrivateKey);

        // Deploy AgentRegistry (ownable, deployer = owner)
        AgentRegistry registry = new AgentRegistry();
        console.log("AgentRegistry deployed at:", address(registry));

        // Deploy PaymentEscrow with Base Sepolia USDC
        PaymentEscrow escrow = new PaymentEscrow(BASE_SEPOLIA_USDC);
        console.log("PaymentEscrow deployed at:", address(escrow));

        vm.stopBroadcast();

        console.log("");
        console.log("=== Deployed Addresses ===");
        console.log("AgentRegistry:", address(registry));
        console.log("PaymentEscrow:", address(escrow));
        console.log("USDC (Base Sepolia):", BASE_SEPOLIA_USDC);
    }
}

/**
 * @notice Deploys MockUSDC + contracts for local/testing purposes
 * @dev Use this when testing locally without Base Sepolia RPC
 */
contract DeployMock is Script {
    function run() external {
        uint256 deployerPrivateKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address deployer = vm.addr(deployerPrivateKey);

        console.log("Deploying AgentPays contracts (Mock USDC)...");
        console.log("Deployer:", deployer);

        vm.startBroadcast(deployerPrivateKey);

        // Deploy mock USDC
        MockUSDC usdc = new MockUSDC();
        console.log("MockUSDC deployed at:", address(usdc));

        // Mint test USDC to deployer
        usdc.mint(deployer, 1_000_000 * 10**6); // 1M mock USDC
        console.log("Minted 1M mock USDC to deployer");

        // Deploy AgentRegistry
        AgentRegistry registry = new AgentRegistry();
        console.log("AgentRegistry deployed at:", address(registry));

        // Deploy PaymentEscrow with mock USDC
        PaymentEscrow escrow = new PaymentEscrow(address(usdc));
        console.log("PaymentEscrow deployed at:", address(escrow));

        vm.stopBroadcast();

        console.log("");
        console.log("=== Deployed Addresses (Mock) ===");
        console.log("MockUSDC:", address(usdc));
        console.log("AgentRegistry:", address(registry));
        console.log("PaymentEscrow:", address(escrow));
    }
}
