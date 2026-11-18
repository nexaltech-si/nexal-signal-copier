"""MetaAPI integration"""
from .trader import MetaAPITrader

# Create instance directly - no lazy loading needed
metaapi_trader = MetaAPITrader()

__all__ = ['metaapi_trader']
