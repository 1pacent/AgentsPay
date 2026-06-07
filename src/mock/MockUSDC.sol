// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/**
 * @title MockUSDC
 * @notice Minimal 6-decimal ERC20 for testing AgentPays contracts
 * @dev Only for use in test environments — NOT production
 */
contract MockUSDC is ERC20 {
    uint8 private constant _DECIMALS = 6;

    constructor() ERC20("Mock USDC", "mUSDC") {}

    function decimals() public view virtual override returns (uint8) {
        return _DECIMALS;
    }

    /// @notice Mint tokens for testing
    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }

    /// @notice Burn tokens
    function burn(address from, uint256 amount) external {
        _burn(from, amount);
    }
}
