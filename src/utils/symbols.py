"""
Canonical symbol normalization.

Single source of truth — previously signal_service and trade_context_manager
each had their own alias map and they had diverged (one knew ETHEREUM/CRUDE,
the other knew EUR/GBP). This is the union of both.
"""

SYMBOL_ALIASES = {
    "GOLD": "XAUUSD",
    "SILVER": "XAGUSD",
    "OIL": "USOIL",
    "CRUDE": "USOIL",
    "BITCOIN": "BTCUSD",
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
    "ETHEREUM": "ETHUSD",
    "EUR": "EURUSD",
    "GBP": "GBPUSD",
}


def normalize_symbol(symbol: str) -> str:
    """Uppercase, strip separators (spaces, dots, slashes), and resolve aliases."""
    if not symbol:
        return symbol
    cleaned = str(symbol).upper().strip().replace(" ", "").replace(".", "").replace("/", "")
    return SYMBOL_ALIASES.get(cleaned, cleaned)
