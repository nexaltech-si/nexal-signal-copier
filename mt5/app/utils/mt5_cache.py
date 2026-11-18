"""Tiny TTL cache for hot MT5 calls.

Each mt5.* call crosses the Linux→Wine IPC boundary (~2-5ms). When the heartbeat,
WebSocket tick worker, health endpoint, and every order placement all call
`account_info()` or `symbol_info_tick(symbol)` redundantly within the same
~100ms window, we can serve them from an in-memory cache and slash IPC traffic.

Defaults are intentionally short (100ms) so freshness for trading decisions is
preserved — a tick that's 100ms old is fine for everything except the actual
order_send call (which still hits MT5 directly).
"""
import os
import threading
import time
from typing import Optional
import MetaTrader5 as mt5

# Per-call TTL in seconds. Override via env var if needed.
ACCOUNT_INFO_TTL = float(os.environ.get("MT5_ACCOUNT_INFO_TTL", 0.1))
TICK_TTL = float(os.environ.get("MT5_TICK_TTL", 0.1))

_lock = threading.Lock()
_account_cache = {"value": None, "expires": 0.0}
_tick_cache: dict = {}  # symbol -> {"value": tick, "expires": ts}


def get_account_info(force: bool = False):
    """Return mt5.account_info() with a short TTL cache.

    Set force=True to bypass the cache (e.g. right before order_send).
    """
    now = time.monotonic()
    if not force:
        with _lock:
            if _account_cache["value"] is not None and _account_cache["expires"] > now:
                return _account_cache["value"]

    info = mt5.account_info()
    with _lock:
        _account_cache["value"] = info
        _account_cache["expires"] = now + ACCOUNT_INFO_TTL
    return info


def get_symbol_tick(symbol: str, force: bool = False):
    """Return mt5.symbol_info_tick(symbol) with a short TTL cache."""
    now = time.monotonic()
    if not force:
        with _lock:
            entry = _tick_cache.get(symbol)
            if entry and entry["expires"] > now:
                return entry["value"]

    tick = mt5.symbol_info_tick(symbol)
    with _lock:
        _tick_cache[symbol] = {"value": tick, "expires": now + TICK_TTL}
    return tick


def invalidate_account():
    """Force the next get_account_info() to hit MT5."""
    with _lock:
        _account_cache["value"] = None
        _account_cache["expires"] = 0.0


def invalidate_tick(symbol: Optional[str] = None):
    """Invalidate one symbol's tick or all of them."""
    with _lock:
        if symbol is None:
            _tick_cache.clear()
        else:
            _tick_cache.pop(symbol, None)
