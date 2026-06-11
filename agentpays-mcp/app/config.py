"""Environment-based configuration with testnet/mainnet switch."""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    # Network
    network: str = field(default_factory=lambda: os.getenv("AGENTPAYS_NETWORK", "testnet"))
    
    # Chain
    rpc_url: str = field(default_factory=lambda: os.getenv(
        "AGENTPAYS_RPC_URL",
        "https://sepolia.infura.io/v3/"  # testnet default
    ))
    chain_id: int = field(default_factory=lambda: int(os.getenv("AGENTPAYS_CHAIN_ID", "11155111")))  # Sepolia
    
    # Smart contract (populated by Track A)
    escrow_contract_address: str | None = field(
        default_factory=lambda: os.getenv("AGENTPAYS_ESCROW_CONTRACT", None)
    )
    
    # Wallet
    wallet_private_key: str | None = field(
        default_factory=lambda: os.getenv("AGENTPAYS_WALLET_PRIVATE_KEY", None)
    )
    wallet_address: str | None = field(
        default_factory=lambda: os.getenv("AGENTPAYS_WALLET_ADDRESS", None)
    )
    
    # Database
    db_path: str = field(default_factory=lambda: os.getenv(
        "AGENTPAYS_DB_PATH",
        str(Path(__file__).parent.parent / "data" / "agentpays.db")
    ))
    
    # Server
    host: str = field(default_factory=lambda: os.getenv("AGENTPAYS_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("AGENTPAYS_PORT", "8000")))
    
    # Mock mode (before Track A deploys)
    mock_contract: bool = field(default_factory=lambda: 
        os.getenv("AGENTPAYS_MOCK_CONTRACT", "true").lower() == "true"
    )
    
    # Pricing (default max for agent discovery)
    default_max_price: float = field(default_factory=lambda: 
        float(os.getenv("AGENTPAYS_DEFAULT_MAX_PRICE", "0.01"))
    )
    
    # Escrow timeout seconds (default 1 hour)
    escrow_timeout_seconds: int = field(default_factory=lambda:
        int(os.getenv("AGENTPAYS_ESCROW_TIMEOUT", "3600"))
    )

    # x402 Bazaar
    x402_bazaar_mcp_url: str = field(
        default_factory=lambda: os.getenv(
            "X402_BAZAAR_MCP_URL",
            "https://api.cdp.coinbase.com/v2/x402/discovery"
        )
    )
    x402_bazaar_http_url: str = field(
        default_factory=lambda: os.getenv(
            "X402_BAZAAR_HTTP_URL",
            "https://api.cdp.coinbase.com/v2/x402/discovery"
        )
    )
    x402_api_key: str | None = field(
        default_factory=lambda: os.getenv("X402_API_KEY", None)
    )


settings = Settings()
