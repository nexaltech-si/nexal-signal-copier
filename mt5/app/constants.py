from enum import Enum

# Use string keys to avoid importing MT5 at module load time outside Windows
# The actual mt5 constants are resolved at runtime in lib.py / routes

MT5_TIMEFRAME_NAMES = [
    'M1','M2','M3','M4','M5','M6','M10','M12','M15','M20','M30',
    'H1','H2','H3','H4','H6','H8','H12','D1','W1','MN1'
]

FILLING_MODE_MAP_KEYS = ["ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN"]

PENDING_ORDER_TYPE_KEYS = [
    "BUY_LIMIT", "SELL_LIMIT",
    "BUY_STOP", "SELL_STOP",
    "BUY_STOP_LIMIT", "SELL_STOP_LIMIT",
]

def build_constants():
    """Call once MT5 is importable (Windows only). Returns dicts of resolved constants."""
    import MetaTrader5 as mt5

    class MT5Timeframe(Enum):
        M1  = mt5.TIMEFRAME_M1
        M2  = mt5.TIMEFRAME_M2
        M3  = mt5.TIMEFRAME_M3
        M4  = mt5.TIMEFRAME_M4
        M5  = mt5.TIMEFRAME_M5
        M6  = mt5.TIMEFRAME_M6
        M10 = mt5.TIMEFRAME_M10
        M12 = mt5.TIMEFRAME_M12
        M15 = mt5.TIMEFRAME_M15
        M20 = mt5.TIMEFRAME_M20
        M30 = mt5.TIMEFRAME_M30
        H1  = mt5.TIMEFRAME_H1
        H2  = mt5.TIMEFRAME_H2
        H3  = mt5.TIMEFRAME_H3
        H4  = mt5.TIMEFRAME_H4
        H6  = mt5.TIMEFRAME_H6
        H8  = mt5.TIMEFRAME_H8
        H12 = mt5.TIMEFRAME_H12
        D1  = mt5.TIMEFRAME_D1
        W1  = mt5.TIMEFRAME_W1
        MN1 = mt5.TIMEFRAME_MN1

    TRADE_RETCODE_DESCRIPTION = {
        mt5.TRADE_RETCODE_REQUOTE:              "Requote",
        mt5.TRADE_RETCODE_REJECT:               "Request rejected",
        mt5.TRADE_RETCODE_CANCEL:               "Request canceled by trader",
        mt5.TRADE_RETCODE_PLACED:               "Order placed",
        mt5.TRADE_RETCODE_DONE:                 "Request completed",
        mt5.TRADE_RETCODE_DONE_PARTIAL:         "Only part of the request was completed",
        mt5.TRADE_RETCODE_ERROR:                "Request processing error",
        mt5.TRADE_RETCODE_TIMEOUT:              "Request canceled by timeout",
        mt5.TRADE_RETCODE_INVALID:              "Invalid request",
        mt5.TRADE_RETCODE_INVALID_VOLUME:       "Invalid volume",
        mt5.TRADE_RETCODE_INVALID_PRICE:        "Invalid price",
        mt5.TRADE_RETCODE_INVALID_STOPS:        "Invalid stops",
        mt5.TRADE_RETCODE_TRADE_DISABLED:       "Trade is disabled",
        mt5.TRADE_RETCODE_MARKET_CLOSED:        "Market is closed",
        mt5.TRADE_RETCODE_NO_MONEY:             "Insufficient funds",
        mt5.TRADE_RETCODE_PRICE_CHANGED:        "Prices changed",
        mt5.TRADE_RETCODE_PRICE_OFF:            "No quotes available",
        mt5.TRADE_RETCODE_INVALID_EXPIRATION:   "Invalid expiration date",
        mt5.TRADE_RETCODE_ORDER_CHANGED:        "Order state changed",
        mt5.TRADE_RETCODE_TOO_MANY_REQUESTS:    "Too many requests",
        mt5.TRADE_RETCODE_NO_CHANGES:           "No changes in request",
        mt5.TRADE_RETCODE_SERVER_DISABLES_AT:   "Autotrading disabled by server",
        mt5.TRADE_RETCODE_CLIENT_DISABLES_AT:   "Autotrading disabled by client",
        mt5.TRADE_RETCODE_LOCKED:               "Request locked",
        mt5.TRADE_RETCODE_FROZEN:               "Order/position frozen",
        mt5.TRADE_RETCODE_INVALID_FILL:         "Invalid filling type",
        mt5.TRADE_RETCODE_CONNECTION:           "No connection with trade server",
        mt5.TRADE_RETCODE_ONLY_REAL:            "Live accounts only",
        mt5.TRADE_RETCODE_LIMIT_ORDERS:         "Pending order limit reached",
        mt5.TRADE_RETCODE_LIMIT_VOLUME:         "Volume limit reached",
        mt5.TRADE_RETCODE_INVALID_ORDER:        "Incorrect order type",
        mt5.TRADE_RETCODE_POSITION_CLOSED:      "Position already closed",
        mt5.TRADE_RETCODE_INVALID_CLOSE_VOLUME: "Close volume exceeds position",
        mt5.TRADE_RETCODE_CLOSE_ORDER_EXIST:    "Close order already exists",
        mt5.TRADE_RETCODE_LIMIT_POSITIONS:      "Open position limit reached",
        mt5.TRADE_RETCODE_REJECT_CANCEL:        "Activation rejected, order canceled",
        mt5.TRADE_RETCODE_LONG_ONLY:            "Only long positions allowed",
        mt5.TRADE_RETCODE_SHORT_ONLY:           "Only short positions allowed",
        mt5.TRADE_RETCODE_CLOSE_ONLY:           "Only position closing allowed",
        mt5.TRADE_RETCODE_FIFO_CLOSE:           "FIFO close rule enforced",
    }

    FILLING_MODE_MAP = {
        "ORDER_FILLING_FOK":    mt5.ORDER_FILLING_FOK,
        "ORDER_FILLING_IOC":    mt5.ORDER_FILLING_IOC,
        "ORDER_FILLING_RETURN": mt5.ORDER_FILLING_RETURN,
    }

    PENDING_ORDER_TYPE_MAP = {
        "BUY_LIMIT":       mt5.ORDER_TYPE_BUY_LIMIT,
        "SELL_LIMIT":      mt5.ORDER_TYPE_SELL_LIMIT,
        "BUY_STOP":        mt5.ORDER_TYPE_BUY_STOP,
        "SELL_STOP":       mt5.ORDER_TYPE_SELL_STOP,
        "BUY_STOP_LIMIT":  mt5.ORDER_TYPE_BUY_STOP_LIMIT,
        "SELL_STOP_LIMIT": mt5.ORDER_TYPE_SELL_STOP_LIMIT,
    }

    return MT5Timeframe, TRADE_RETCODE_DESCRIPTION, FILLING_MODE_MAP, PENDING_ORDER_TYPE_MAP


# order_send retcodes that mean the request WAS accepted: DONE, PLACED (pending order), DONE_PARTIAL.
# Treating only 10009 as success reported placed pending orders / partial fills as failures,
# which makes the caller retry and create duplicates.
TRADE_OK_RETCODES = (10008, 10009, 10010)
