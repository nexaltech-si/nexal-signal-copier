"""
Per-trade asyncio lock to prevent concurrent SL/TP modifications.

Both order_sync_service and position_monitor_service run on the same event
loop. Without coordination, they can both call modify_position on the same
trade in the same cycle — last write wins and silently discards the other.

Usage:
    async with trade_modification_lock(trade_id):
        await trading_provider.modify_position(...)
        await db_service.update_trade_field(trade_id, ...)
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Dict
from loguru import logger


_locks: Dict[str, asyncio.Lock] = {}


def _get_lock(trade_id: str) -> asyncio.Lock:
    if trade_id not in _locks:
        _locks[trade_id] = asyncio.Lock()
    return _locks[trade_id]


@asynccontextmanager
async def trade_modification_lock(trade_id: str, caller: str = ""):
    """
    Async context manager that serialises broker modify_position calls
    for a given trade. If another coroutine holds the lock, this one
    waits rather than racing.
    """
    lock = _get_lock(trade_id)
    if lock.locked() and caller:
        logger.debug(f"🔒 [{caller}] waiting for trade lock on {trade_id[:8]}...")
    async with lock:
        yield


def release_trade_lock(trade_id: str) -> None:
    """Remove the lock entry once a trade is fully closed (memory hygiene)."""
    _locks.pop(trade_id, None)
