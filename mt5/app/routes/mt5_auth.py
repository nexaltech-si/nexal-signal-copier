"""MT5 broker login / logout / session-status API."""
from flask import Blueprint, jsonify, request
import logging
from flasgger import swag_from

from middleware.auth import require_api_key
from errors import ValidationError
from utils.error_handler import format_error_response, get_request_context
from utils.validation_schemas import validate_request, MT5LoginSchema
from services.mt5_session import login as mt5_login, logout as mt5_logout, status as mt5_status
from swagger_specs import (
    mt5_login_spec, mt5_logout_spec, mt5_login_status_spec,
)

mt5_auth_bp = Blueprint("mt5_auth", __name__)
logger = logging.getLogger(__name__)


@mt5_auth_bp.route("/mt5/login", methods=["POST"])
@require_api_key
@swag_from(mt5_login_spec)
def login_endpoint():
    try:
        data = request.get_json(silent=True)
        if not data:
            raise ValidationError(
                "JSON body required",
                endpoint="/mt5/login",
                request_context=get_request_context(request),
            )

        validated = validate_request(MT5LoginSchema(), data, endpoint="/mt5/login")

        result = mt5_login(
            login_id=validated["login"],
            password=validated["password"],
            server=validated["server"],
            path=validated.get("path"),
            timeout=validated["timeout"],
        )

        if result.get("ok"):
            return jsonify(result), 200
        return jsonify(result), 401  # invalid creds / unreachable server

    except ValidationError as e:
        return format_error_response(e, 400)
    except Exception as e:
        logger.error("mt5_login: %s", e)
        return format_error_response(e, 500, endpoint="/mt5/login",
                                     request_context=get_request_context(request))


@mt5_auth_bp.route("/mt5/logout", methods=["POST"])
@require_api_key
@swag_from(mt5_logout_spec)
def logout_endpoint():
    try:
        return jsonify(mt5_logout()), 200
    except Exception as e:
        logger.error("mt5_logout: %s", e)
        return format_error_response(e, 500, endpoint="/mt5/logout",
                                     request_context=get_request_context(request))


@mt5_auth_bp.route("/mt5/login_status", methods=["GET"])
@require_api_key
@swag_from(mt5_login_status_spec)
def login_status_endpoint():
    try:
        return jsonify(mt5_status()), 200
    except Exception as e:
        logger.error("mt5_login_status: %s", e)
        return format_error_response(e, 500, endpoint="/mt5/login_status",
                                     request_context=get_request_context(request))
