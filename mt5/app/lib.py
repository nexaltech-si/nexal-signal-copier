import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import pytz
import logging
import os

logger = logging.getLogger(__name__)

from constants import TRADE_OK_RETCODES

MT5_TIMEZONE = pytz.utc
BROKER_TIMEZONE_OFFSET = int(os.getenv("BROKER_TIMEZONE_OFFSET", "3"))


def parse_iso_datetime(s: str) -> datetime:
    """Parse ISO datetime string and return aware UTC datetime for MT5 API. Adds broker offset when no date provided."""
    if not s or not isinstance(s, str):
        return datetime.now(MT5_TIMEZONE) + timedelta(hours=BROKER_TIMEZONE_OFFSET)
    
    # Strip whitespace
    s = s.strip()
    
    try:
        # Parse the datetime string, handling 'Z' suffix
        dt_str = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
        
        # If it has no timezone info, assume UTC and localize
        if dt.tzinfo is None:
            dt = MT5_TIMEZONE.localize(dt)
        else:
            # Convert to UTC
            dt = dt.astimezone(MT5_TIMEZONE)
            
        return dt
    except ValueError:
        logger.error(f"Failed to parse datetime '{s}', falling back to now")
        return datetime.now(MT5_TIMEZONE)


def get_timeframe(timeframe_str: str) -> int:
    mapping = {
        "M1":  1, "M2":  2,  "M3":  3,  "M4":  4,
        "M5":  5, "M6":  6,  "M10": 10, "M12": 12,
        "M15": 15,"M20": 20, "M30": 30,
        "H1":  mt5.TIMEFRAME_H1,  "H2":  mt5.TIMEFRAME_H2,
        "H3":  mt5.TIMEFRAME_H3,  "H4":  mt5.TIMEFRAME_H4,
        "H6":  mt5.TIMEFRAME_H6,  "H8":  mt5.TIMEFRAME_H8,
        "H12": mt5.TIMEFRAME_H12,
        "D1":  mt5.TIMEFRAME_D1,  "W1":  mt5.TIMEFRAME_W1,
        "MN1": mt5.TIMEFRAME_MN1,
    }
    key = timeframe_str.upper()
    if key not in mapping:
        raise ValueError(f"Invalid timeframe: {timeframe_str}")
    return mapping[key]


_symbol_selected_cache: set = set()  # symbols confirmed visible; cleared on MT5 reconnect


def ensure_symbol_selected(symbol: str) -> bool:
    """Ensure a symbol is selected in Market Watch before data operations.

    Caches successful selections in-process so the mt5.symbol_info() IPC call
    is skipped on repeat requests (the common case after the first fetch).
    """
    if symbol in _symbol_selected_cache:
        return True

    sym_info = mt5.symbol_info(symbol)
    if sym_info is None:
        logger.warning("Symbol %s not found in MT5 terminal", symbol)
        return False

    if not sym_info.visible:
        logger.info("Symbol %s exists but not visible, attempting to select", symbol)
        if not mt5.symbol_select(symbol, True):
            ec, es = mt5.last_error()
            logger.warning("Failed to select symbol %s: MT5 error code=%s, error=%s", symbol, ec, es)
            return False

    _symbol_selected_cache.add(symbol)
    return True


def _get_filling_mode(symbol: str) -> int:
    sym_info = mt5.symbol_info(symbol)
    if sym_info is not None and hasattr(sym_info, "filling_mode"):
        fm = sym_info.filling_mode
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        elif fm & 2:
            return mt5.ORDER_FILLING_IOC
        else:
            return mt5.ORDER_FILLING_RETURN
    return mt5.ORDER_FILLING_RETURN


def resolve_filling_mode(raw, symbol: str) -> int:
    FILLING_MAP = {
        "ORDER_FILLING_FOK":    mt5.ORDER_FILLING_FOK,
        "ORDER_FILLING_IOC":    mt5.ORDER_FILLING_IOC,
        "ORDER_FILLING_RETURN": mt5.ORDER_FILLING_RETURN,
    }
    if raw is not None:
        if isinstance(raw, str) and raw in FILLING_MAP:
            return FILLING_MAP[raw]
        if isinstance(raw, int):
            return raw
    return _get_filling_mode(symbol)


def close_position(position, deviation=20, magic=0, comment="", type_filling=None, volume=None):
    if "type" not in position or "ticket" not in position:
        logger.error("Position dict missing type or ticket.")
        return None
    close_type_dict = {0: mt5.ORDER_TYPE_SELL, 1: mt5.ORDER_TYPE_BUY}
    position_type = int(position["type"])
    if position_type not in close_type_dict:
        logger.error(f"Unknown position type: {position_type}")
        return None
    tick = mt5.symbol_info_tick(position["symbol"])
    if tick is None:
        logger.error("Failed to get tick for %s", position["symbol"])
        return None
    price = tick.ask if position_type == 1 else tick.bid
    if price == 0.0:
        logger.error("Invalid price for %s", position["symbol"])
        return None
    close_volume = float(volume) if volume is not None else float(position["volume"])
    filling = resolve_filling_mode(type_filling, position["symbol"])
    trade_request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "position":     int(position["ticket"]),
        "symbol":       position["symbol"],
        "volume":       close_volume,
        "type":         close_type_dict[position_type],
        "price":        price,
        "deviation":    int(deviation),
        "magic":        int(magic),
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }
    # Comment field omitted - MT5 broker may reject certain comment formats
    # Check MT5 connection before sending order
    if not mt5.terminal_info():
        logger.error("MT5 terminal not connected - cannot close position %s", position["ticket"])
        return None
    
    result = mt5.order_send(trade_request)
    if result is None or result.retcode not in TRADE_OK_RETCODES:
        msg = result.comment if result else "no result"
        retcode = result.retcode if result else "N/A"
        # Get MT5 last error for more context
        ec, es = mt5.last_error()
        logger.error("Failed to close position %s (symbol=%s, volume=%s): retcode=%s, msg=%s, mt5_error_code=%s, mt5_error=%s", 
                     position["ticket"], position["symbol"], close_volume, retcode, msg, ec, es)
        return None
    logger.info("Position %s closed (vol=%s).", position["ticket"], close_volume)
    return result


def close_all_positions(order_type="all", magic=None, type_filling=None):
    order_type_dict = {"BUY": mt5.ORDER_TYPE_BUY, "SELL": mt5.ORDER_TYPE_SELL}
    total = mt5.positions_total()
    if not total:
        return []
    positions = mt5.positions_get()
    if positions is None:
        return []
    df = pd.DataFrame([p._asdict() for p in positions])
    if magic is not None:
        df = df[df["magic"] == int(magic)]
    if order_type != "all":
        if order_type not in order_type_dict:
            return []
        df = df[df["type"] == order_type_dict[order_type]]
    if df.empty:
        return []
    results = []
    for _, pos in df.iterrows():
        res = close_position(pos, type_filling=type_filling)
        if res:
            results.append(res)
    return results


def close_buy_positions(magic=None):
    """Closes all BUY (Long) positions."""
    return close_all_positions(order_type="BUY", magic=magic)


def close_sell_positions(magic=None):
    """Closes all SELL (Short) positions."""
    return close_all_positions(order_type="SELL", magic=magic)


def close_all_profitable_positions(magic=None):
    """Closes only positions that are currently in profit."""
    df = get_positions(magic=magic)
    if df.empty:
        return []
    
    # Filter for profit > 0
    df = df[df["profit"] > 0]
    
    results = []
    for _, pos in df.iterrows():
        res = close_position(pos, comment="Equity Protection: Closing Profit")
        if res:
            results.append(res)
    return results


def close_losing_positions(magic=None):
    """Closes only positions that are currently in loss."""
    df = get_positions(magic=magic)
    if df.empty:
        return []
    
    # Filter for profit < 0
    df = df[df["profit"] < 0]
    
    results = []
    for _, pos in df.iterrows():
        res = close_position(pos, comment="Equity Protection: Closing Loss")
        if res:
            results.append(res)
    return results


def close_positions_by_symbol(symbol, magic=None):
    """Closes all positions for a specific symbol."""
    df = get_positions(magic=magic)
    if df.empty:
        return []
    
    # Filter by symbol
    df = df[df["symbol"] == symbol]
    
    results = []
    for _, pos in df.iterrows():
        res = close_position(pos, comment=f"Equity Protection: Closing {symbol}")
        if res:
            results.append(res)
    return results


def normalize_price(symbol, price):
    """Round a price to the symbol's digits (MT5 rejects prices with extra decimals).
    Returns the price unchanged if the symbol info is unavailable."""
    if price is None:
        return None
    try:
        info = mt5.symbol_info(symbol)
        if info is not None and getattr(info, "digits", None) is not None:
            return round(float(price), int(info.digits))
    except Exception:
        logger.debug("normalize_price failed for %s", symbol, exc_info=True)
    return float(price)


class MT5ReadError(Exception):
    """MT5 failed to answer a read (as opposed to answering 'nothing there')."""


RES_S_OK = 1  # MetaTrader5.last_error() code for "Success"


def mt5_read_failed(result) -> bool:
    """True when an MT5 read returned None because of an ERROR. The Python API returns None both on
    error and (for some calls/builds) when there is simply nothing, so the last_error() code decides:
    RES_S_OK means 'nothing there', anything else is a real failure."""
    if result is not None:
        return False
    try:
        return mt5.last_error()[0] != RES_S_OK
    except Exception:
        return True


def get_positions_strict(magic=None):
    """Like get_positions(), but raises MT5ReadError when MT5 FAILS instead of returning an empty
    frame. positions_get() returns None on error and () when flat - callers (the bot's order sync)
    must be able to tell those apart, otherwise a failed read looks like a flat account."""
    total = mt5.positions_total()
    if mt5_read_failed(total):
        raise MT5ReadError("positions_total() failed: %s" % (mt5.last_error(),))
    if not total:
        return get_positions(magic)
    positions = mt5.positions_get()
    if mt5_read_failed(positions):
        raise MT5ReadError("positions_get() failed: %s" % (mt5.last_error(),))
    if not positions:
        return get_positions(magic)
    df = pd.DataFrame([p._asdict() for p in positions])
    if magic is not None:
        df = df[df["magic"] == int(magic)]
    return df


def get_positions(magic=None):
    empty_cols = ["ticket","time","time_msc","time_update","time_update_msc","type",
                  "magic","identifier","reason","volume","price_open","sl","tp",
                  "price_current","swap","profit","symbol","comment","external_id"]
    total = mt5.positions_total()
    if not total:
        return pd.DataFrame(columns=empty_cols)
    positions = mt5.positions_get()
    if positions is None:
        return pd.DataFrame(columns=empty_cols)
    df = pd.DataFrame([p._asdict() for p in positions])
    if magic is not None:
        df = df[df["magic"] == int(magic)]
    return df


def serialize_positions_df(df):
    if df.empty:
        return []
    records = df.to_dict(orient="records")
    for rec in records:
        for col in ["time","time_msc","time_update","time_update_msc"]:
            if col in rec and rec[col]:
                try:
                    divisor = 1000 if "msc" in col else 1
                    rec[col] = datetime.fromtimestamp(rec[col]/divisor, tz=MT5_TIMEZONE).isoformat()
                except Exception:
                    pass
    return records


def get_deal_from_ticket(ticket, from_date=None, to_date=None):
    if not isinstance(ticket, int):
        return None
    if from_date is None or to_date is None:
        to_date   = datetime.now(MT5_TIMEZONE) + timedelta(hours=BROKER_TIMEZONE_OFFSET)
        from_date = to_date - timedelta(days=30)
    deals = mt5.history_deals_get(int(from_date.timestamp()), int(to_date.timestamp()), position=ticket)
    if not deals:
        return None
    df = pd.DataFrame([d._asdict() for d in deals])
    if df.empty:
        return None
    return {
        "ticket":      ticket,
        "symbol":      df["symbol"].iloc[0],
        "type":        "BUY" if df["type"].iloc[0] == 0 else "SELL",
        "volume":      float(df["volume"].sum()),
        "open_time":   datetime.fromtimestamp(df["time"].min(), tz=MT5_TIMEZONE).isoformat(),
        "close_time":  datetime.fromtimestamp(df["time"].max(), tz=MT5_TIMEZONE).isoformat(),
        "open_price":  float(df["price"].iloc[0]),
        "close_price": float(df["price"].iloc[-1]),
        "profit":      float(df["profit"].sum()),
        "commission":  float(df["commission"].sum()),
        "swap":        float(df["swap"].sum()),
        "comment":     str(df["comment"].iloc[-1]),
    }


def get_order_from_ticket(ticket):
    if not isinstance(ticket, int):
        return None
    orders = mt5.history_orders_get(ticket=ticket)
    if not orders:
        return None
    return orders[0]._asdict()


def close_all_orders(magic=None, symbol=None, order_type=None):
    """
    Cancel all pending orders with optional filtering.
    
    Args:
        magic: Filter by magic number (optional)
        symbol: Filter by symbol (optional)
        order_type: Filter by order type (optional, e.g., "BUY_LIMIT", "SELL_STOP", etc.)
    
    Returns:
        List of MT5 trade results for each cancellation attempt
    """
    # Map order type strings to MT5 constants
    order_type_map = {
        "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
        "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
        "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
        "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
        "BUY_STOP_LIMIT": mt5.ORDER_TYPE_BUY_STOP_LIMIT,
        "SELL_STOP_LIMIT": mt5.ORDER_TYPE_SELL_STOP_LIMIT,
    }
    
    # Get all pending orders
    orders = mt5.orders_get()
    if orders is None:
        logger.warning("No pending orders found")
        return []
    
    # Convert to DataFrame for filtering
    df = pd.DataFrame([o._asdict() for o in orders])
    if df.empty:
        return []
    
    # Apply filters
    if magic is not None:
        df = df[df["magic"] == int(magic)]
    if symbol is not None:
        df = df[df["symbol"] == symbol]
    if order_type is not None and order_type in order_type_map:
        df = df[df["type"] == order_type_map[order_type]]
    
    if df.empty:
        logger.info("No pending orders match the filters")
        return []
    
    results = []
    for _, order in df.iterrows():
        req = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": int(order["ticket"]),
        }
        result = mt5.order_send(req)
        if result is not None and result.retcode in TRADE_OK_RETCODES:
            results.append(result)
            logger.info("Cancelled order %s", order["ticket"])
        else:
            ec, es = mt5.last_error()
            logger.error("Failed to cancel order %s: retcode=%s %s", order["ticket"],
                         getattr(result, "retcode", None), es)
    
    logger.info("Cancelled %d/%d orders", len(results), len(df))
    return results
