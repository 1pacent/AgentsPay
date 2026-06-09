"""Wallet abstraction for AgentPays MVP.

MVP: Simple ECDSA private key loaded from env var.
Future: Crossmint SDK / Coinbase Agentic Wallet.
"""

from eth_account import Account
from eth_account.signers.local import LocalAccount

from app.config import settings


def get_account() -> LocalAccount | None:
    """Return the wallet account, or None if no key configured."""
    key = settings.wallet_private_key
    if not key:
        return None
    return Account.from_key(key)


def get_address() -> str | None:
    """Return the wallet address, or configured override."""
    if settings.wallet_address:
        return settings.wallet_address
    account = get_account()
    if account:
        return account.address
    return None


def sign_message(message: str) -> str | None:
    """Sign a message for verification purposes."""
    account = get_account()
    if not account:
        return None
    signed = account.sign_message(
        Account._unsafe_sign_msg(message.encode())  # simple MVP
    )
    return signed.signature.hex()
