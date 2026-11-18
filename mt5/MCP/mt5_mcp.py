"""
mt5_mcp — MCP server for MetaTrader 5 REST + WebSocket API
Covers every REST endpoint exposed by the MT5 Flask container.

Configuration (environment variables):
  MT5_API_URL   Base URL of the MT5 container  (default: http://localhost:5002)
  MT5_API_KEY   X-API-Key for authenticated endpoints (optional but recommended)
"""

import json
import os
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------
mcp = FastMCP("mt5_mcp")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MT5_API_URL = os.environ.get("MT5_API_URL", "http://localhost:5002").rstrip("/")
MT5_API_KEY = os.environ.get("MT5_API_KEY", "")
DEFAULT_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Shared HTTP client helpers
# ---------------------------------------------------------------------------
def _headers() -> Dict[str, str]:
    h: Dict[str, str] = {"Content-Type": "application/json"}
    if MT5_API_KEY:
        h["X-API-Key"] = MT5_API_KEY
    return h


async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> str:
    url = f"{MT5_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.get(url, headers=_headers(), params=params)
            r.raise_for_status()
            return r.text
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}", "detail": e.response.text})
    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def _post(path: str, body: Optional[Dict[str, Any]] = None) -> str:
    url = f"{MT5_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.post(url, headers=_headers(), json=body or {})
            r.raise_for_status()
            return r.text
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}", "detail": e.response.text})
    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


async def _put(path: str, body: Optional[Dict[str, Any]] = None) -> str:
    url = f"{MT5_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            r = await client.put(url, headers=_headers(), json=body or {})
            r.raise_for_status()
            return r.text
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}", "detail": e.response.text})
    except httpx.TimeoutException:
        return json.dumps({"error": "Request timed out"})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ===========================================================================
# ── HEALTH & SYSTEM ──────────────────────────────────────────────────────────
# ===========================================================================

@mcp.tool(
    name="mt5_health",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_health() -> str:
    """Check MT5 API health and connection status.

    Returns JSON with keys: status, mt5_connected, mt5_initialized.
    Use this first to confirm the container and terminal are reachable.
    """
    return await _get("/health")


@mcp.tool(
    name="mt5_version",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_version() -> str:
    """Return MT5 terminal build, date and revision numbers."""
    return await _get("/version")


@mcp.tool(
    name="mt5_account_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_account_info() -> str:
    """Return current MT5 account details: balance, equity, margin, leverage, profit, currency, etc."""
    return await _get("/account_info")


@mcp.tool(
    name="mt5_terminal_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_terminal_info() -> str:
    """Return MT5 terminal information: build number, paths, connection flags."""
    return await _get("/terminal_info")


@mcp.tool(
    name="mt5_last_error",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_last_error() -> str:
    """Return the last MT5 error code and message. Useful for debugging failed operations."""
    return await _get("/last_error")


# ===========================================================================
# ── MT5 SESSION (LOGIN / LOGOUT / STATUS) ────────────────────────────────────
# ===========================================================================

class MT5LoginInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    login: int = Field(..., description="Broker account number (e.g. 12345678)", gt=0)
    password: str = Field(..., description="Trading or investor password", min_length=1, max_length=128)
    server: str = Field(..., description="Exact broker server name, case-sensitive (e.g. 'ICMarketsSC-Demo')", min_length=1, max_length=128)
    path: Optional[str] = Field(None, description="Optional absolute path to terminal64.exe inside Wine (leave blank for auto-detect)")
    timeout: int = Field(60000, description="Initialize timeout in milliseconds", ge=1000, le=300000)


@mcp.tool(
    name="mt5_login",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def mt5_login(params: MT5LoginInput) -> str:
    """Log into a broker account on the MT5 terminal.

    Credentials are stored in-process memory (and on disk if MT5_PERSIST_LOGIN=1).
    The equity-protection heartbeat reuses these credentials for auto-reconnect.

    Args:
        params: MT5LoginInput with login, password, server (required) + optional path/timeout.

    Returns:
        JSON with ok (bool), login, server, account info on success; error message on failure.
    """
    body: Dict[str, Any] = {
        "login": params.login,
        "password": params.password,
        "server": params.server,
        "timeout": params.timeout,
    }
    if params.path:
        body["path"] = params.path
    return await _post("/mt5/login", body)


@mcp.tool(
    name="mt5_logout",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_logout() -> str:
    """Disconnect from the broker and forget stored credentials."""
    return await _post("/mt5/logout")


@mcp.tool(
    name="mt5_login_status",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_login_status() -> str:
    """Return current MT5 session status: logged_in, login, server, connected, account info, last_error.
    Password is never returned.
    """
    return await _get("/mt5/login_status")


# ===========================================================================
# ── SYMBOLS & MARKET BOOK ────────────────────────────────────────────────────
# ===========================================================================

class SymbolSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    group: str = Field("*", description="Symbol group pattern with wildcards, e.g. '*USD*', 'Forex*'")


@mcp.tool(
    name="mt5_get_symbols",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_get_symbols() -> str:
    """Return all symbols currently in Market Watch."""
    return await _get("/symbols")


@mcp.tool(
    name="mt5_search_symbols",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_search_symbols(params: SymbolSearchInput) -> str:
    """Search symbols by a group pattern (supports wildcards).

    Args:
        params: SymbolSearchInput with group pattern (e.g. '*USD*', '*XAU*', 'Metals*').

    Returns:
        JSON array of matching symbol name strings.
    """
    return await _get("/symbols/search", params={"group": params.group})


class SymbolNameInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol name, e.g. 'XAUUSD', 'EURUSD'", min_length=1, max_length=32)


@mcp.tool(
    name="mt5_symbol_info",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_symbol_info(params: SymbolNameInput) -> str:
    """Return full symbol specification: digits, contract size, spread, swap rates, margin, etc.

    Args:
        params: SymbolNameInput with symbol name.
    """
    return await _get(f"/symbol_info/{params.symbol}")


@mcp.tool(
    name="mt5_symbol_tick",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_symbol_tick(params: SymbolNameInput) -> str:
    """Return the latest bid/ask tick for a symbol.

    Args:
        params: SymbolNameInput with symbol name.
    """
    return await _get(f"/symbol_info_tick/{params.symbol}")


@mcp.tool(
    name="mt5_market_book",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_market_book(params: SymbolNameInput) -> str:
    """Return the Depth-of-Market (DOM / order book) for a symbol.

    Args:
        params: SymbolNameInput with symbol name.
    """
    return await _get(f"/market_book/{params.symbol}")


# ===========================================================================
# ── MARKET DATA ───────────────────────────────────────────────────────────────
# ===========================================================================

VALID_TIMEFRAMES = [
    "M1","M2","M3","M4","M5","M6","M10","M12","M15","M20","M30",
    "H1","H2","H3","H4","H6","H8","H12","D1","W1","MN1",
]


class FetchDataPosInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol name, e.g. 'XAUUSD'", min_length=1, max_length=32)
    timeframe: str = Field("H1", description="Timeframe: M1 M5 M15 M30 H1 H4 D1 W1 MN1 (and more)")
    num_bars: int = Field(100, description="Number of OHLCV bars to fetch (1–10000)", ge=1, le=10000)

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        v = v.upper()
        if v not in VALID_TIMEFRAMES:
            raise ValueError(f"Invalid timeframe '{v}'. Valid values: {VALID_TIMEFRAMES}")
        return v


@mcp.tool(
    name="mt5_fetch_ohlcv",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_fetch_ohlcv(params: FetchDataPosInput) -> str:
    """Fetch OHLCV candlestick bars working backwards from the current bar.

    Args:
        params: FetchDataPosInput with symbol, timeframe and num_bars.

    Returns:
        JSON array of bars with time (ISO), open, high, low, close, tick_volume, spread, real_volume.
    """
    return await _get("/fetch_data_pos", params={
        "symbol": params.symbol,
        "timeframe": params.timeframe,
        "num_bars": params.num_bars,
    })


class FetchDataRangeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol name", min_length=1, max_length=32)
    timeframe: str = Field("H1", description="Timeframe: M1 M5 M15 M30 H1 H4 D1 W1 MN1")
    from_date: str = Field(..., description="Start datetime ISO 8601, e.g. '2026-01-01T00:00:00Z'")
    to_date: str = Field(..., description="End datetime ISO 8601, e.g. '2026-01-31T23:59:59Z'")

    @field_validator("timeframe")
    @classmethod
    def validate_timeframe(cls, v: str) -> str:
        v = v.upper()
        if v not in VALID_TIMEFRAMES:
            raise ValueError(f"Invalid timeframe '{v}'.")
        return v


@mcp.tool(
    name="mt5_fetch_ohlcv_range",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_fetch_ohlcv_range(params: FetchDataRangeInput) -> str:
    """Fetch OHLCV bars between two ISO datetime strings.

    Args:
        params: FetchDataRangeInput with symbol, timeframe, from_date, to_date.
    """
    return await _get("/fetch_data_range", params={
        "symbol": params.symbol,
        "timeframe": params.timeframe,
        "from_date": params.from_date,
        "to_date": params.to_date,
    })


class FetchTicksInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol name", min_length=1, max_length=32)
    from_date: str = Field(..., description="Start datetime ISO 8601")
    count: int = Field(1000, description="Number of ticks (1–100000)", ge=1, le=100000)
    flags: int = Field(1, description="Tick flags: 1=INFO, 2=TRADE, 3=ALL", ge=0, le=3)


@mcp.tool(
    name="mt5_fetch_ticks",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_fetch_ticks(params: FetchTicksInput) -> str:
    """Fetch raw tick data starting from a datetime.

    Args:
        params: FetchTicksInput with symbol, from_date, count, flags.
    """
    return await _get("/fetch_ticks", params={
        "symbol": params.symbol,
        "from_date": params.from_date,
        "count": params.count,
        "flags": params.flags,
    })


class FetchTicksRangeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol name", min_length=1, max_length=32)
    from_date: str = Field(..., description="Start datetime ISO 8601")
    to_date: str = Field(..., description="End datetime ISO 8601")
    flags: int = Field(1, description="Tick flags: 1=INFO, 2=TRADE, 3=ALL", ge=0, le=3)


@mcp.tool(
    name="mt5_fetch_ticks_range",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_fetch_ticks_range(params: FetchTicksRangeInput) -> str:
    """Fetch raw tick data between two datetime strings.

    Args:
        params: FetchTicksRangeInput with symbol, from_date, to_date, flags.
    """
    return await _get("/fetch_ticks_range", params={
        "symbol": params.symbol,
        "from_date": params.from_date,
        "to_date": params.to_date,
        "flags": params.flags,
    })


# ===========================================================================
# ── POSITIONS ─────────────────────────────────────────────────────────────────
# ===========================================================================

@mcp.tool(
    name="mt5_positions_total",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_positions_total() -> str:
    """Return the count of currently open positions."""
    return await _get("/positions_total")


class MagicFilterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    magic: Optional[int] = Field(None, description="Filter by magic number (EA identifier). Omit to return all.", ge=0, le=2147483647)


@mcp.tool(
    name="mt5_get_positions",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_get_positions(params: MagicFilterInput = MagicFilterInput()) -> str:
    """Return all open positions, optionally filtered by magic number.

    Args:
        params: MagicFilterInput with optional magic number.

    Returns:
        JSON array of position objects with ticket, symbol, type, volume, price_open, sl, tp, profit, etc.
    """
    p: Dict[str, Any] = {}
    if params.magic is not None:
        p["magic"] = params.magic
    return await _get("/get_positions", params=p or None)


@mcp.tool(
    name="mt5_get_pending_orders",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_get_pending_orders(params: MagicFilterInput) -> str:
    """Return all pending orders, optionally filtered by magic number.

    Args:
        params: MagicFilterInput with optional magic number.
    """
    p: Dict[str, Any] = {}
    if params.magic is not None:
        p["magic"] = params.magic
    return await _get("/get_orders", params=p or None)


class ClosePositionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: int = Field(..., description="Position ticket number", gt=0)
    symbol: str = Field(..., description="Symbol name, e.g. 'XAUUSD'", min_length=1, max_length=32)
    type: int = Field(..., description="Position type: 0=BUY, 1=SELL", ge=0, le=1)
    volume: float = Field(..., description="Full position volume (as shown in get_positions)", gt=0)


@mcp.tool(
    name="mt5_close_position",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_close_position(params: ClosePositionInput) -> str:
    """Close a specific open position fully.

    Args:
        params: ClosePositionInput with ticket, symbol, type (0=BUY/1=SELL), volume.

    Returns:
        JSON with message and MT5 order_send result (retcode, deal, order, price, comment).
    """
    body = {
        "position": {
            "ticket": params.ticket,
            "symbol": params.symbol,
            "type": params.type,
            "volume": params.volume,
        }
    }
    return await _post("/close_position", body)


class ClosePartialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: int = Field(..., description="Position ticket number", gt=0)
    symbol: str = Field(..., description="Symbol name", min_length=1, max_length=32)
    type: int = Field(..., description="Position type: 0=BUY, 1=SELL", ge=0, le=1)
    position_volume: float = Field(..., description="Current full volume of the position", gt=0)
    close_volume: float = Field(..., description="Volume to close (must be less than position_volume)", gt=0)


@mcp.tool(
    name="mt5_close_partial",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_close_partial(params: ClosePartialInput) -> str:
    """Partially close an open position.

    Args:
        params: ClosePartialInput — ticket, symbol, type, position_volume (full), close_volume (partial).
    """
    body = {
        "position": {
            "ticket": params.ticket,
            "symbol": params.symbol,
            "type": params.type,
            "volume": params.position_volume,
        },
        "volume": params.close_volume,
    }
    return await _post("/close_partial", body)


class CloseAllPositionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_type: str = Field("all", description="Filter: 'all', 'BUY', or 'SELL'")
    magic: Optional[int] = Field(None, description="Optional magic number filter", ge=0)

    @field_validator("order_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"all", "BUY", "SELL"}
        if v not in allowed:
            raise ValueError(f"order_type must be one of {allowed}")
        return v


@mcp.tool(
    name="mt5_close_all_positions",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_close_all_positions(params: CloseAllPositionsInput) -> str:
    """Close all open positions (or filter by BUY/SELL and/or magic number).

    Args:
        params: CloseAllPositionsInput with order_type ('all'/'BUY'/'SELL') and optional magic.
    """
    body: Dict[str, Any] = {"order_type": params.order_type}
    if params.magic is not None:
        body["magic"] = params.magic
    return await _post("/close_all_positions", body)


@mcp.tool(
    name="mt5_close_profitable_positions",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_close_profitable_positions(params: MagicFilterInput) -> str:
    """Close only positions currently in profit.

    Args:
        params: MagicFilterInput with optional magic number filter.
    """
    body: Dict[str, Any] = {}
    if params.magic is not None:
        body["magic"] = params.magic
    return await _post("/close_profitable", body)


@mcp.tool(
    name="mt5_close_losing_positions",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_close_losing_positions(params: MagicFilterInput) -> str:
    """Close only positions currently in a loss.

    Args:
        params: MagicFilterInput with optional magic number filter.
    """
    body: Dict[str, Any] = {}
    if params.magic is not None:
        body["magic"] = params.magic
    return await _post("/close_losing", body)


class CloseSymbolInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol to close all positions for, e.g. 'XAUUSD'", min_length=1, max_length=32)
    magic: Optional[int] = Field(None, description="Optional magic number filter", ge=0)


@mcp.tool(
    name="mt5_close_symbol_positions",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_close_symbol_positions(params: CloseSymbolInput) -> str:
    """Close all positions for a specific symbol.

    Args:
        params: CloseSymbolInput with symbol and optional magic.
    """
    body: Dict[str, Any] = {"symbol": params.symbol}
    if params.magic is not None:
        body["magic"] = params.magic
    return await _post("/close_symbol", body)


class ModifySLTPInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: int = Field(..., description="Position ticket number", gt=0)
    sl: Optional[float] = Field(None, description="New Stop Loss price (0 to remove)", ge=0)
    tp: Optional[float] = Field(None, description="New Take Profit price (0 to remove)", ge=0)


@mcp.tool(
    name="mt5_modify_sl_tp",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_modify_sl_tp(params: ModifySLTPInput) -> str:
    """Modify the Stop Loss and/or Take Profit on an open position.

    Args:
        params: ModifySLTPInput with position ticket, optional sl and/or tp price.
    """
    body: Dict[str, Any] = {"position": params.position}
    if params.sl is not None:
        body["sl"] = params.sl
    if params.tp is not None:
        body["tp"] = params.tp
    return await _post("/modify_sl_tp", body)


# ===========================================================================
# ── ORDERS ────────────────────────────────────────────────────────────────────
# ===========================================================================

class MarketOrderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol name, e.g. 'XAUUSD'", min_length=1, max_length=32)
    volume: float = Field(..., description="Lot size (e.g. 0.01, 0.1, 1.0)", ge=0.01, le=100)
    type: str = Field(..., description="'BUY' or 'SELL'")
    sl: Optional[float] = Field(None, description="Stop Loss price (optional but recommended)", ge=0)
    tp: Optional[float] = Field(None, description="Take Profit price (optional)", ge=0)
    deviation: int = Field(20, description="Max price slippage in points", ge=0, le=1000)
    magic: int = Field(0, description="Magic number / EA identifier", ge=0, le=2147483647)
    comment: str = Field("", description="Order comment (max 128 chars)", max_length=128)
    type_filling: Optional[str] = Field(None, description="Filling mode: ORDER_FILLING_FOK | ORDER_FILLING_IOC | ORDER_FILLING_RETURN (auto-detected if omitted)")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        v = v.upper()
        if v not in {"BUY", "SELL"}:
            raise ValueError("type must be 'BUY' or 'SELL'")
        return v


@mcp.tool(
    name="mt5_market_order",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
)
async def mt5_market_order(params: MarketOrderInput) -> str:
    """Execute a market BUY or SELL order immediately at current price.

    Trading will be refused if equity protection has blocked the account.

    Args:
        params: MarketOrderInput with symbol, volume, type (BUY/SELL), optional sl/tp/deviation/magic/comment.

    Returns:
        JSON with message and result: retcode, deal ticket, order ticket, filled price.
    """
    body: Dict[str, Any] = {
        "symbol": params.symbol,
        "volume": params.volume,
        "type": params.type,
        "deviation": params.deviation,
        "magic": params.magic,
        "comment": params.comment,
    }
    if params.sl is not None:
        body["sl"] = params.sl
    if params.tp is not None:
        body["tp"] = params.tp
    if params.type_filling:
        body["type_filling"] = params.type_filling
    return await _post("/order", body)


class PendingOrderInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol name", min_length=1, max_length=32)
    volume: float = Field(..., description="Lot size", ge=0.01, le=100)
    type: str = Field(..., description="BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | BUY_STOP_LIMIT | SELL_STOP_LIMIT")
    price: float = Field(..., description="Order trigger price", gt=0)
    stoplimit_price: Optional[float] = Field(None, description="Required for *_STOP_LIMIT orders: the limit price after trigger", gt=0)
    sl: Optional[float] = Field(None, description="Stop Loss price", ge=0)
    tp: Optional[float] = Field(None, description="Take Profit price", ge=0)
    deviation: int = Field(20, ge=0, le=1000)
    magic: int = Field(0, ge=0, le=2147483647)
    comment: str = Field("", max_length=128)
    expiration: Optional[str] = Field(None, description="Order expiration datetime ISO 8601, e.g. '2026-12-31T23:59:59Z'")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        v = v.upper()
        allowed = {"BUY_LIMIT","SELL_LIMIT","BUY_STOP","SELL_STOP","BUY_STOP_LIMIT","SELL_STOP_LIMIT"}
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}")
        return v


@mcp.tool(
    name="mt5_pending_order",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def mt5_pending_order(params: PendingOrderInput) -> str:
    """Place a pending order (LIMIT / STOP / STOP_LIMIT).

    Args:
        params: PendingOrderInput with symbol, volume, type, price, optional sl/tp/expiration.

    Returns:
        JSON with message and result on success; error details on failure.
    """
    body: Dict[str, Any] = {
        "symbol": params.symbol,
        "volume": params.volume,
        "type": params.type,
        "price": params.price,
        "deviation": params.deviation,
        "magic": params.magic,
        "comment": params.comment,
    }
    if params.stoplimit_price is not None:
        body["stoplimit_price"] = params.stoplimit_price
    if params.sl is not None:
        body["sl"] = params.sl
    if params.tp is not None:
        body["tp"] = params.tp
    if params.expiration:
        body["expiration"] = params.expiration
    return await _post("/limit_order", body)


class CancelOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: int = Field(..., description="Pending order ticket number to cancel", gt=0)


@mcp.tool(
    name="mt5_cancel_order",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_cancel_order(params: CancelOrderInput) -> str:
    """Cancel a pending order by ticket number.

    Args:
        params: CancelOrderInput with ticket.
    """
    return await _post("/cancel_order", {"ticket": params.ticket})


class ModifyOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: int = Field(..., description="Pending order ticket number to modify", gt=0)
    price: Optional[float] = Field(None, description="New trigger price", gt=0)
    sl: Optional[float] = Field(None, description="New Stop Loss price", ge=0)
    tp: Optional[float] = Field(None, description="New Take Profit price", ge=0)
    stoplimit_price: Optional[float] = Field(None, description="New stoplimit price (for STOP_LIMIT orders)", gt=0)
    expiration: Optional[str] = Field(None, description="New expiration datetime ISO 8601")


@mcp.tool(
    name="mt5_modify_order",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_modify_order(params: ModifyOrderInput) -> str:
    """Modify price, SL, TP, or expiration on an existing pending order.

    Args:
        params: ModifyOrderInput with ticket plus any fields to change.
    """
    body: Dict[str, Any] = {"ticket": params.ticket}
    if params.price is not None:
        body["price"] = params.price
    if params.sl is not None:
        body["sl"] = params.sl
    if params.tp is not None:
        body["tp"] = params.tp
    if params.stoplimit_price is not None:
        body["stoplimit_price"] = params.stoplimit_price
    if params.expiration:
        body["expiration"] = params.expiration
    return await _post("/modify_order", body)


class CloseAllOrdersInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    magic: Optional[int] = Field(None, description="Filter by magic number", ge=0)
    symbol: Optional[str] = Field(None, description="Filter by symbol", max_length=32)
    order_type: Optional[str] = Field(None, description="Filter by type: BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | BUY_STOP_LIMIT | SELL_STOP_LIMIT")


@mcp.tool(
    name="mt5_cancel_all_orders",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_cancel_all_orders(params: CloseAllOrdersInput) -> str:
    """Cancel all pending orders, optionally filtered by magic, symbol, or order type.

    Args:
        params: CloseAllOrdersInput with optional magic, symbol, order_type filters.
    """
    body: Dict[str, Any] = {}
    if params.magic is not None:
        body["magic"] = params.magic
    if params.symbol:
        body["symbol"] = params.symbol
    if params.order_type:
        body["order_type"] = params.order_type
    return await _post("/close_all_orders", body)


# ===========================================================================
# ── HISTORY ───────────────────────────────────────────────────────────────────
# ===========================================================================

class HistoryDealsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    from_date: str = Field(..., description="Start datetime ISO 8601, e.g. '2026-01-01T00:00:00Z'")
    to_date: str = Field(..., description="End datetime ISO 8601")
    position: Optional[int] = Field(None, description="Filter by position ticket (strict match)", gt=0)
    symbol: Optional[str] = Field(None, description="Filter by symbol", max_length=32)
    magic: Optional[int] = Field(None, description="Filter by magic number", ge=0)


@mcp.tool(
    name="mt5_history_deals",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_history_deals(params: HistoryDealsInput) -> str:
    """Return historical deals in a date range with optional filters.

    Args:
        params: HistoryDealsInput with from_date, to_date, and optional position/symbol/magic filters.

    Returns:
        JSON array of deal objects: ticket, order, time, type, entry, volume, price, profit, commission, swap.
    """
    p: Dict[str, Any] = {"from_date": params.from_date, "to_date": params.to_date}
    if params.position is not None:
        p["position"] = params.position
    if params.symbol:
        p["symbol"] = params.symbol
    if params.magic is not None:
        p["magic"] = params.magic
    return await _get("/history_deals_get", params=p)


class HistoryOrdersInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    ticket: Optional[int] = Field(None, description="Order ticket — use this OR date range", gt=0)
    from_date: Optional[str] = Field(None, description="Start datetime ISO 8601 (required if no ticket)")
    to_date: Optional[str] = Field(None, description="End datetime ISO 8601 (required if no ticket)")


@mcp.tool(
    name="mt5_history_orders",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_history_orders(params: HistoryOrdersInput) -> str:
    """Return historical orders by ticket OR by date range (provide one or the other).

    Args:
        params: HistoryOrdersInput with ticket OR (from_date + to_date).
    """
    p: Dict[str, Any] = {}
    if params.ticket is not None:
        p["ticket"] = params.ticket
    if params.from_date:
        p["from_date"] = params.from_date
    if params.to_date:
        p["to_date"] = params.to_date
    return await _get("/history_orders_get", params=p)


class TicketInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: int = Field(..., description="Position or order ticket number", gt=0)


@mcp.tool(
    name="mt5_deal_from_ticket",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_deal_from_ticket(params: TicketInput) -> str:
    """Get aggregated P&L summary for a position ticket (open + close deals combined).

    Args:
        params: TicketInput with ticket.
    """
    return await _get("/get_deal_from_ticket", params={"ticket": params.ticket})


@mcp.tool(
    name="mt5_order_from_ticket",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_order_from_ticket(params: TicketInput) -> str:
    """Get the historical order record for a specific ticket.

    Args:
        params: TicketInput with ticket.
    """
    return await _get("/get_order_from_ticket", params={"ticket": params.ticket})


class AccountStatsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    from_date: str = Field(..., description="Start datetime ISO 8601")
    to_date: str = Field(..., description="End datetime ISO 8601")


@mcp.tool(
    name="mt5_account_stats",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_account_stats(params: AccountStatsInput) -> str:
    """Calculate trading statistics over a date range.

    Args:
        params: AccountStatsInput with from_date and to_date (ISO 8601).

    Returns:
        JSON with: total_trades, wins, losses, win_rate, total_profit, gross_profit, gross_loss,
        profit_factor, avg_win, avg_loss, total_commission, total_swap.
    """
    return await _get("/account_stats", params={"from_date": params.from_date, "to_date": params.to_date})


# ===========================================================================
# ── TRADE LIFECYCLE ───────────────────────────────────────────────────────────
# ===========================================================================

class TradeLifecycleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket: int = Field(..., description="Position or order ticket", gt=0)
    days_back: int = Field(30, description="Number of days to search history (1–365)", ge=1, le=365)


@mcp.tool(
    name="mt5_trade_lifecycle",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_trade_lifecycle(params: TradeLifecycleInput) -> str:
    """Get the complete lifecycle of a trade: pending order → position → deals → closed status.

    Args:
        params: TradeLifecycleInput with ticket and optional days_back.

    Returns:
        JSON with status, pending_order, position, order_history, deals, and summary (entry/exit price, net P&L).
    """
    return await _get("/trade_lifecycle", params={"ticket": params.ticket, "days_back": params.days_back})


@mcp.tool(
    name="mt5_trade_status",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_trade_status(params: TicketInput) -> str:
    """Quick status check for a trade: PENDING | RUNNING | CLOSED_PROFIT | CLOSED_LOSS | CLOSED_BREAKEVEN | CANCELED | EXPIRED | REJECTED | UNKNOWN.

    Args:
        params: TicketInput with ticket.
    """
    return await _get("/trade_status", params={"ticket": params.ticket})


class BatchStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tickets: List[int] = Field(..., description="List of position or order ticket numbers (max 100)", min_length=1, max_length=100)


@mcp.tool(
    name="mt5_batch_trade_status",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_batch_trade_status(params: BatchStatusInput) -> str:
    """Get status for multiple trades in one call (efficient for monitoring many positions).

    Args:
        params: BatchStatusInput with list of ticket numbers.
    """
    return await _post("/trade_batch_status", {"tickets": params.tickets})


class TradeSearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    from_date: Optional[str] = Field(None, description="Start datetime ISO 8601 (default: 7 days ago)")
    to_date: Optional[str] = Field(None, description="End datetime ISO 8601 (default: now)")
    symbol: Optional[str] = Field(None, description="Filter by symbol", max_length=32)
    magic: Optional[int] = Field(None, description="Filter by magic number", ge=0)
    status: Optional[str] = Field(None, description="Filter by status: CLOSED_PROFIT | CLOSED_LOSS | CLOSED_BREAKEVEN")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"CLOSED_PROFIT", "CLOSED_LOSS", "CLOSED_BREAKEVEN"}:
            raise ValueError("status must be CLOSED_PROFIT, CLOSED_LOSS, or CLOSED_BREAKEVEN")
        return v


@mcp.tool(
    name="mt5_trade_search",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_trade_search(params: TradeSearchInput) -> str:
    """Search closed trades by symbol, magic, date range, or P&L status.

    Args:
        params: TradeSearchInput with optional symbol, magic, from_date, to_date, status filters.

    Returns:
        JSON with trades array and count. Each trade has: position_id, ticket, symbol, type,
        entry_time, exit_time, entry_price, exit_price, volume, profit, commission, swap, net_pnl.
    """
    p: Dict[str, Any] = {}
    if params.from_date:
        p["from_date"] = params.from_date
    if params.to_date:
        p["to_date"] = params.to_date
    if params.symbol:
        p["symbol"] = params.symbol
    if params.magic is not None:
        p["magic"] = params.magic
    if params.status:
        p["status"] = params.status
    return await _get("/trade_search", params=p or None)


# ===========================================================================
# ── SEASONAL ANALYSIS ─────────────────────────────────────────────────────────
# ===========================================================================

class SeasonalInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol name, e.g. 'XAUUSD', 'EURUSD'", min_length=1, max_length=32)
    years: int = Field(20, description="Number of years of D1 history to analyse (1–30)", ge=1, le=30)


@mcp.tool(
    name="mt5_seasonal_analysis",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_seasonal_analysis(params: SeasonalInput) -> str:
    """Compute monthly seasonal tendencies (win probability + average return) for a symbol.

    Args:
        params: SeasonalInput with symbol and optional years (default 20).

    Returns:
        JSON with pair, years list, months list, probability (% bullish per month),
        avg_return (% per month), and year-by-year returns matrix.
    """
    return await _get(f"/seasonal/{params.symbol}", params={"years": params.years})


# ===========================================================================
# ── EQUITY PROTECTION ─────────────────────────────────────────────────────────
# ===========================================================================

@mcp.tool(
    name="mt5_protection_status",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_protection_status() -> str:
    """Return current equity protection status for the active account.

    Returns:
        JSON with: account_number, trading_blocked, daily_drawdown_pct, total_drawdown_pct,
        balance, equity, margin_level, historical_peak, max limits, action, block_reason.
    """
    return await _get("/protection/status")


@mcp.tool(
    name="mt5_protection_config",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_protection_config() -> str:
    """Return current equity protection configuration (limits, mode, intervals, action)."""
    return await _get("/protection/config")


class ProtectionConfigUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_daily_loss_pct: Optional[float] = Field(None, description="Max daily loss % (e.g. 3.0 for 3%)", gt=0, le=100)
    max_total_drawdown_pct: Optional[float] = Field(None, description="Max total drawdown % from peak", gt=0, le=100)
    max_daily_loss_abs: Optional[float] = Field(None, description="Max daily loss in account currency (0 = disabled)", ge=0)
    max_total_drawdown_abs: Optional[float] = Field(None, description="Max total drawdown in account currency (0 = disabled)", ge=0)
    min_margin_level_pct: Optional[float] = Field(None, description="Minimum margin level % (0 = disabled)", ge=0)
    protection_mode: Optional[str] = Field(None, description="'equity' or 'balance'")
    action: Optional[str] = Field(None, description="Action on breach: close_all | notify_only | close_losing | close_profitable")
    heartbeat_interval: Optional[float] = Field(None, description="Seconds between checks (min 0.01)", ge=0.01)
    ws_update_interval: Optional[float] = Field(None, description="Seconds between WebSocket equity updates", ge=0)
    auto_reset_daily: Optional[bool] = Field(None, description="Auto-unblock at midnight")
    verbose_logging: Optional[bool] = Field(None, description="Enable verbose protection logs")
    enabled: Optional[bool] = Field(None, description="Enable or disable the protection service")


@mcp.tool(
    name="mt5_update_protection_config",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_update_protection_config(params: ProtectionConfigUpdateInput) -> str:
    """Update equity protection configuration with hot-reload (changes take effect immediately).

    Args:
        params: ProtectionConfigUpdateInput — provide only the fields you want to change.
    """
    body = {k: v for k, v in params.model_dump().items() if v is not None}
    return await _put("/protection/config", body)


@mcp.tool(
    name="mt5_protection_enable",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_protection_enable() -> str:
    """Start the equity protection monitoring heartbeat."""
    return await _post("/protection/enable")


@mcp.tool(
    name="mt5_protection_disable",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_protection_disable() -> str:
    """Stop the equity protection monitoring heartbeat."""
    return await _post("/protection/disable")


class ResetBlockInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    account_number: Optional[str] = Field(None, description="Account number to unblock (default: current account)", max_length=32)


@mcp.tool(
    name="mt5_reset_trading_block",
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_reset_trading_block(params: ResetBlockInput) -> str:
    """Manually unblock trading for an account after equity protection has fired.

    Args:
        params: ResetBlockInput with optional account_number (defaults to current account).
    """
    body: Dict[str, Any] = {}
    if params.account_number:
        body["account_number"] = params.account_number
    return await _post("/protection/reset_block", body)


@mcp.tool(
    name="mt5_protection_all_accounts",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_protection_all_accounts() -> str:
    """Return protection status for all accounts with historical data stored on disk."""
    return await _get("/protection/accounts")


@mcp.tool(
    name="mt5_liquidate_all",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_liquidate_all() -> str:
    """PANIC BUTTON: Close all positions AND cancel all pending orders immediately.

    Use this for emergency risk reduction. Equity protection block is NOT required.
    """
    return await _post("/protection/close/all")


@mcp.tool(
    name="mt5_liquidate_profitable",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_liquidate_profitable() -> str:
    """Manually close all positions currently in profit (lock in gains)."""
    return await _post("/protection/close/profitable")


@mcp.tool(
    name="mt5_liquidate_losing",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_liquidate_losing() -> str:
    """Manually close all positions currently in a loss (cut losses)."""
    return await _post("/protection/close/losing")


class LiquidateSymbolInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    symbol: str = Field(..., description="Symbol to liquidate, e.g. 'XAUUSD'", min_length=1, max_length=32)


@mcp.tool(
    name="mt5_liquidate_symbol",
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
)
async def mt5_liquidate_symbol(params: LiquidateSymbolInput) -> str:
    """Manually close all positions for a specific symbol.

    Args:
        params: LiquidateSymbolInput with symbol name.
    """
    return await _post("/protection/close/symbol", {"symbol": params.symbol})


# ===========================================================================
# ── METRICS & DIAGNOSTICS ────────────────────────────────────────────────────
# ===========================================================================

@mcp.tool(
    name="mt5_metrics",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_metrics() -> str:
    """Return API performance metrics: total requests, error rate, response time percentiles, per-endpoint counts."""
    return await _get("/metrics")


@mcp.tool(
    name="mt5_metrics_health",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_metrics_health() -> str:
    """Return API health score, status (healthy/degraded/unhealthy), uptime, and error count."""
    return await _get("/metrics/health")


@mcp.tool(
    name="mt5_websocket_status",
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
)
async def mt5_websocket_status() -> str:
    """Return the number of connected WebSocket clients and their current symbol/position/order subscriptions."""
    return await _get("/ws/status")


# ===========================================================================
# ── Entry point ──────────────────────────────────────────────────────────────
# ===========================================================================
if __name__ == "__main__":
    mcp.run()
