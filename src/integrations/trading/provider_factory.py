"""
Trading provider access.

``create_trading_provider()`` returns the single shared, hot-switchable provider proxy
(see provider_manager). Every service gets the SAME connected provider, and switching
TRADING_PROVIDER (MetaAPI <-> MT5 REST) at runtime applies to all of them at once.
"""
from src.integrations.trading.base_provider import BaseTradingProvider


def create_trading_provider() -> BaseTradingProvider:
    from src.integrations.trading.provider_manager import provider_manager
    return provider_manager.proxy
