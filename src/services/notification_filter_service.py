"""
Notification Filter Service

Single source of truth for which notification categories are allowed to reach the
Telegram notification channel. Every send that goes through
``UnifiedNotificationSender`` is tagged with a category and checked here first.

Categories are stored as individual BOOL rows in the ``settings`` table so they
render as plain switches on the dashboard config page and hot-reload with the
rest of the settings.

Design notes:
  * Unknown / untagged sends are ALWAYS delivered — a missing tag must never
    silence a notification by accident.
  * Interactive prompts (trade approval, brain-action approval, symbol picker)
    are deliberately NOT filterable: dropping them would stall the trading flow
    with no way for the user to intervene. See ``ALWAYS_ON_METHODS``.
  * Defaults are all "true", so existing installs behave exactly as before until
    the user turns something off.
"""
from typing import Any, Dict, Optional, Tuple

from loguru import logger


# Master switch — when off, every filterable category is suppressed.
MASTER_KEY = "NOTIFY_ENABLED"

# category id -> (setting key, label, description)
# The order here is the order the switches appear on the dashboard.
NOTIFICATION_CATEGORIES: Dict[str, Tuple[str, str, str]] = {
    "signal_received": (
        "NOTIFY_SIGNAL_RECEIVED",
        "New Signal Detected",
        "A new signal was picked up from a monitored channel",
    ),
    "signal_rejected": (
        "NOTIFY_SIGNAL_REJECTED",
        "Signal Rejected / Filtered",
        "Signal blocked by risk manager, news filter, drawdown protection, validator or the Brain",
    ),
    "signal_parse_failed": (
        "NOTIFY_SIGNAL_PARSE_FAILED",
        "Signal Extraction Failed",
        "The AI could not extract a valid signal from a message or chart",
    ),
    "brain_decision": (
        "NOTIFY_BRAIN_DECISIONS",
        "Brain Signal Adjustments",
        "The Trading Brain modified a signal's entry, stop loss or take profit before execution",
    ),
    "trade_executed": (
        "NOTIFY_TRADE_EXECUTED",
        "Trade Opened",
        "A trade was successfully placed on the account",
    ),
    "trade_failed": (
        "NOTIFY_TRADE_FAILED",
        "Trade Execution Failed",
        "Order rejected by the broker, or the trading provider could not be reached",
    ),
    "trade_closed": (
        "NOTIFY_TRADE_CLOSED",
        "Trade Closed",
        "Position closed, with final profit/loss",
    ),
    "order_cancelled": (
        "NOTIFY_ORDER_CANCELLED",
        "Pending Order Cancelled",
        "A pending order was cancelled or expired before filling",
    ),
    "rr_milestone": (
        "NOTIFY_RR_MILESTONES",
        "R:R Milestones",
        "Position reached 1:1 or 1:2 risk-to-reward",
    ),
    "position_management": (
        "NOTIFY_POSITION_MANAGEMENT",
        "Position Management",
        "Stop loss / take profit moves, partial closes, breakeven and trailing stop updates",
    ),
    "approval_outcome": (
        "NOTIFY_APPROVAL_OUTCOMES",
        "Approval Outcomes",
        "Approval requests that timed out or were rejected (the approval prompts themselves are always sent)",
    ),
    "trade_plans": (
        "NOTIFY_TRADE_PLANS",
        "Trade Plan Updates",
        "Plans registered, filtered, executed, expired or falling back to a secondary entry",
    ),
    "command_response": (
        "NOTIFY_COMMAND_RESPONSES",
        "Command Confirmations",
        "Replies confirming manual commands you sent to the bot",
    ),
    "ai_analysis": (
        "NOTIFY_AI_ANALYSIS",
        "AI Market Analysis",
        "Periodic market analysis and recommendations from the AI",
    ),
    "errors": (
        "NOTIFY_ERRORS",
        "Errors & Connection Failures",
        "Internal errors, connection/API failures and service-unavailable warnings",
    ),
    "risk_alerts": (
        "NOTIFY_RISK_ALERTS",
        "Risk & Drawdown Alerts",
        "Drawdown limit breaches and risk-management warnings",
    ),
    "bot_lifecycle": (
        "NOTIFY_BOT_LIFECYCLE",
        "Bot Started / Stopped",
        "Startup banner and shutdown notice",
    ),
}

# Sends that must never be filtered — they need a human response to continue.
ALWAYS_ON_METHODS = {
    "notify_approval_request",
    "notify_brain_action_approval",
    "notify_missed_command",
    "send_symbol_picker",
}

# Default category for the typed notify_* methods on UnifiedNotificationSender.
# Generic send_message() callers pass category= explicitly instead.
METHOD_CATEGORY_MAP: Dict[str, str] = {
    "notify_signal_received": "signal_received",
    "notify_signal_rejected": "signal_rejected",
    "notify_trade_executed": "trade_executed",
    "notify_trade_failed": "trade_failed",
    "notify_position_closed": "trade_closed",
    "notify_approval_timeout": "approval_outcome",
    "notify_approval_confirmed": "approval_outcome",
    "notify_error": "errors",
    "notify_risk_warning": "risk_alerts",
    "notify_daily_summary": "ai_analysis",
    "notify_bot_started": "bot_lifecycle",
    "notify_bot_stopped": "bot_lifecycle",
}


def setting_key(category: str) -> Optional[str]:
    """Return the settings-table key backing a category id."""
    entry = NOTIFICATION_CATEGORIES.get(category)
    return entry[0] if entry else None


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


async def _get_bool_setting(key: str, default: bool = True) -> bool:
    """Read a BOOL setting, defaulting to ``default`` if unavailable."""
    try:
        from src.services.settings_service import settings_service

        if settings_service is None:
            return default
        return _as_bool(await settings_service.get_setting(key, default), default)
    except Exception as e:
        # Never let a settings hiccup swallow a notification.
        logger.debug(f"Notification filter: could not read {key} ({e}), allowing send")
        return default


async def is_category_enabled(category: Optional[str]) -> bool:
    """
    True if notifications for ``category`` should be delivered.

    Untagged sends (``category is None``) and unknown category ids are always
    allowed, so adding a new send site can never silently disable it.
    """
    if not category:
        return True
    key = setting_key(category)
    if not key:
        logger.debug(f"Notification filter: unknown category '{category}', allowing send")
        return True

    if not await _get_bool_setting(MASTER_KEY, True):
        return False
    return await _get_bool_setting(key, True)


async def should_send(method_name: str, category: Optional[str] = None) -> bool:
    """
    Resolve the category for a send and report whether it is allowed.

    ``category`` (passed explicitly by generic send_message callers) wins over the
    method-name default.
    """
    if method_name in ALWAYS_ON_METHODS:
        return True
    return await is_category_enabled(category or METHOD_CATEGORY_MAP.get(method_name))
