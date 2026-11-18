from flask import Blueprint, jsonify
import MetaTrader5 as mt5
import logging
from flasgger import swag_from
from middleware.auth import require_api_key
from swagger_specs import last_error_spec

error_bp = Blueprint("error", __name__)
logger = logging.getLogger(__name__)


@error_bp.route("/last_error")
@require_api_key
@swag_from(last_error_spec)
def last_error():
    try:
        code, msg = mt5.last_error()
        return jsonify({"error_code": code, "error_message": msg})
    except Exception as e:
        logger.error("last_error: %s", e)
        return jsonify({"error": "Internal server error"}), 500
