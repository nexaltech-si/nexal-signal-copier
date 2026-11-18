"""
Canonical pip-size lookup.

Single source of truth for string-based pip sizes — previously this mapping
was copy-pasted in 9 places and had drifted (trading_brain was missing JPY
and crypto entirely; order_sync checked categories in a different order).

IMPORTANT: Pips vs Points for standard accounts
- Most forex pairs: 1 pip = 0.0001 (4th decimal); 0.00001 is a POINT, not a pip
- JPY/HUF/CZK pairs + Silver (XAG) / Platinum (XPT) / Palladium (XPD): 1 pip = 0.01 (digits=3)
- Gold (XAU) / crypto (BTC/ETH): 1 pip = 0.1

Note: risk_service additionally derives pip size from live broker
specifications (digits/tick value/contract size); that logic stays there —
this function is the shared string-based path and the broker-spec fallback.
"""

DEFAULT_PIP_SIZE = 0.0001

# Checked in order: JPY-style quotes first (majority behavior of the
# previous copies), then metals/crypto.
# XAG/XPD/XPT (silver/palladium/platinum) have pip=0.01 (digits=3, same as JPY pairs).
_PIP_001 = ('JPY', 'HUF', 'CZK', 'XAG', 'SILVER', 'XPD', 'XPT')
_PIP_01 = ('XAU', 'GOLD', 'BTC', 'ETH')


def get_pip_size(symbol) -> float:
    """Return the pip size for a symbol based on its name."""
    if not symbol:
        return DEFAULT_PIP_SIZE
    sym = str(symbol).upper()
    if any(cur in sym for cur in _PIP_001):
        return 0.01
    if any(cur in sym for cur in _PIP_01):
        return 0.1
    return DEFAULT_PIP_SIZE
