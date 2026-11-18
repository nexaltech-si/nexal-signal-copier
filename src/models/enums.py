"""
Enumerations for trading signals and orders
"""
from enum import Enum


class SignalAction(str, Enum):
    """Trading signal action types"""
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    MODIFY = "MODIFY"


class OrderType(str, Enum):
    """Order type for trading"""
    BUY = "BUY"
    SELL = "SELL"


class SignalStatus(str, Enum):
    """Signal processing status"""
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class SignalType(str, Enum):
    """Legacy signal type (kept for backwards compatibility)"""
    BUY = "BUY"
    SELL = "SELL"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"
    CLOSE = "CLOSE"


class CalculationMethod(str, Enum):
    """Calculation method for TP/SL"""
    PIPS = "PIPS"
    RR = "RR"  # Risk-Reward ratio


class TrailingActivationMethod(str, Enum):
    """Method to activate trailing stop"""
    PROFIT_PIPS = "PROFIT_PIPS"  # Activate after X pips profit
    PROFIT_RR = "PROFIT_RR"  # Activate after X:1 RR profit
    PARTIAL_TP = "PARTIAL_TP"  # Activate after partial TP hit
    IMMEDIATE = "IMMEDIATE"  # Activate immediately


class BreakevenTriggerMethod(str, Enum):
    """Method to trigger breakeven"""
    AFTER_PARTIAL = "AFTER_PARTIAL"  # Move to BE only after auto partial is taken
    PROFIT_PIPS = "PROFIT_PIPS"  # Move to BE after X pips profit
    AFTER_SIBLING_TP_HIT = "AFTER_SIBLING_TP_HIT"  # Move to BE when sibling trades from same signal hit TP (multi-TP signals)


class TradeActionType(str, Enum):
    """Types of trade actions"""
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CANCEL = "CANCEL"
    MODIFY_SL = "MODIFY_SL"
    MODIFY_TP = "MODIFY_TP"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    TRAILING_STOP = "TRAILING_STOP"
    BREAKEVEN = "BREAKEVEN"
    LOCK_PROFIT = "LOCK_PROFIT"
    AUTO_TP = "AUTO_TP"
    AUTO_PARTIAL = "AUTO_PARTIAL"
