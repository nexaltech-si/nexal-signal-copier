import os
import logging
import secrets
from functools import wraps
from typing import Optional
from flask import request, jsonify

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("MT5_API_KEY", "")
# Explicit opt-out for local development only. An empty MT5_API_KEY on its own
# no longer disables auth — this API places real orders (audit finding C-01).
AUTH_DISABLED = os.environ.get("MT5_API_AUTH_DISABLED", "").lower() == "true"

if not API_KEY and not AUTH_DISABLED:
    logger.critical(
        "MT5_API_KEY is not set — every protected endpoint will return 503. "
        "Set MT5_API_KEY (and MT5_REST_API_KEY on the bot/dashboard), or "
        "MT5_API_AUTH_DISABLED=true for local development only."
    )
elif AUTH_DISABLED:
    logger.warning("MT5_API_AUTH_DISABLED=true — API authentication is OFF. Never use this in production.")


def is_valid_api_key(key: Optional[str]) -> bool:
    """Constant-time check of a presented key. True when auth is explicitly disabled."""
    if AUTH_DISABLED:
        return True
    if not API_KEY or not key:
        return False
    return secrets.compare_digest(key, API_KEY)


def extract_api_key(headers, auth: Optional[dict] = None) -> Optional[str]:
    """Key from X-API-Key, Authorization: Bearer, or a Socket.IO auth payload."""
    key = headers.get("X-API-Key")
    if not key:
        authz = headers.get("Authorization", "")
        if authz.startswith("Bearer "):
            key = authz[len("Bearer "):]
    if not key and isinstance(auth, dict):
        key = auth.get("apiKey") or auth.get("api_key")
    return key or None


def require_api_key(f):
    """Decorator – enforces X-API-Key header. Fails closed when no key is configured."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not API_KEY and not AUTH_DISABLED:
            return jsonify({"error": "Service misconfigured: MT5_API_KEY not set"}), 503
        if not is_valid_api_key(extract_api_key(request.headers)):
            logger.warning("Unauthorized request from %s", request.remote_addr)
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def require_trading_not_blocked(f):
    """Decorator – rejects order placement when equity protection has blocked trading.

    Holds protection.lock for the full duration of the wrapped handler so the
    heartbeat thread cannot flip the block flag (or run a liquidation) between
    the check and the order_send. This closes the race window where a freshly
    blocked account could still slip an order through.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        from services.equity_protection import get_protection_service
        protection = get_protection_service()
        if protection is None:
            return f(*args, **kwargs)

        # Refresh current account before checking (cheap MT5 call; protects against
        # stale current_account when a different terminal session is now active).
        try:
            protection.update_current_account()
        except Exception:
            pass

        with protection.lock:
            if protection.is_trading_blocked():
                reason = protection.last_notification_reasons.get(
                    protection.current_account, "Trading blocked by equity protection"
                )
                logger.warning(
                    "Blocked order attempt on account %s: %s",
                    protection.current_account, reason,
                )
                return jsonify({"error": "Trading blocked", "reason": reason}), 403
            # Also refuse to place orders while a liquidation is mid-flight.
            if getattr(protection, "is_liquidating", False):
                return jsonify({
                    "error": "Trading blocked",
                    "reason": "Equity protection is liquidating positions; retry after completion."
                }), 409
            return f(*args, **kwargs)
    return decorated
