from flask import Blueprint, jsonify
import MetaTrader5 as mt5
import logging
from flasgger import swag_from
from middleware.auth import require_api_key
from utils.mt5_cache import get_account_info as cached_account_info
from swagger_specs import (
    health_check_spec, account_info_spec,
    terminal_info_spec, version_spec
)

health_bp = Blueprint("health", __name__)
logger = logging.getLogger(__name__)


@health_bp.route("/health")
@health_bp.route("/")
@swag_from(health_check_spec)
def health_check():
    terminal = mt5.terminal_info()
    initialized = terminal is not None and terminal.connected
    return jsonify({
        "status": "healthy",
        "mt5_connected": initialized,
        "mt5_initialized": initialized,
    }), 200


@health_bp.route("/account_info")
@require_api_key
@swag_from(account_info_spec)
def account_info():
    try:
        info = cached_account_info()
        if info is None:
            return jsonify({"error": "Failed to get account info"}), 500
        d = info._asdict()
        return jsonify({
            "login":          d.get("login"),
            "server":         d.get("server"),
            "currency":       d.get("currency"),
            "leverage":       d.get("leverage"),
            "balance":        d.get("balance"),
            "credit":         d.get("credit"),
            "profit":         d.get("profit"),
            "equity":         d.get("equity"),
            "margin":         d.get("margin"),
            "margin_free":    d.get("margin_free"),
            "margin_level":   d.get("margin_level"),
            "margin_so_call": d.get("margin_so_call"),
            "margin_so_so":   d.get("margin_so_so"),
            "trade_allowed":  d.get("trade_allowed"),
            "trade_expert":   d.get("trade_expert"),
            "limit_orders":   d.get("limit_orders"),
        })
    except Exception as e:
        logger.error("account_info: %s", e)
        return jsonify({"error": "Failed to get account info"}), 500


@health_bp.route("/terminal_info")
@require_api_key
@swag_from(terminal_info_spec)
def terminal_info():
    try:
        terminal = mt5.terminal_info()
        if terminal is None:
            return jsonify({"error": "Failed to get terminal info"}), 500
        return jsonify(terminal._asdict())
    except Exception as e:
        logger.error("terminal_info: %s", e)
        return jsonify({"error": "Failed to get terminal info"}), 500


@health_bp.route("/version")
@swag_from(version_spec)
def version():
    ver = mt5.version()
    if ver is None:
        return jsonify({"error": "Failed to get version"}), 500
    return jsonify({"build": ver[0], "date": ver[1], "revision": ver[2]})

