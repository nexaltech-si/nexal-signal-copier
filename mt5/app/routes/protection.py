from flask import Blueprint, jsonify, request
import logging
from flasgger import swag_from
from middleware.auth import require_api_key
from services.equity_protection import get_protection_service
from utils.error_handler import format_error_response, get_request_context
from errors import ValidationError
from swagger_specs import (
    get_protection_config_spec, update_protection_config_spec,
    enable_protection_spec, disable_protection_spec,
    get_protection_status_spec, get_all_accounts_status_spec,
    reset_account_block_spec, toggle_verbose_logging_spec,
    manual_close_all_spec, manual_close_profitable_spec,
    manual_close_losing_spec, manual_close_symbol_spec
)

protection_bp = Blueprint("protection", __name__)
logger = logging.getLogger(__name__)


@protection_bp.route("/protection/config", methods=["GET"])
@require_api_key
@swag_from(get_protection_config_spec)
def get_protection_config():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        config = protection.get_config()
        return jsonify(config), 200
    except Exception as e:
        logger.error("get_protection_config: %s", e)
        return format_error_response(e, 500, endpoint="/protection/config", request_context=get_request_context(request))


@protection_bp.route("/protection/config", methods=["PUT", "POST"])
@require_api_key
@swag_from(update_protection_config_spec)
def update_protection_config():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        data = request.get_json()
        if not data:
            raise ValidationError("JSON body required", endpoint="/protection/config", request_context=get_request_context(request))
        
        # Validate protection_mode if provided
        if 'protection_mode' in data:
            if data['protection_mode'] not in ['equity', 'balance']:
                raise ValidationError("protection_mode must be 'equity' or 'balance'", 
                                   endpoint="/protection/config", 
                                   request_context=get_request_context(request))
        
        # Validate numeric values
        if 'max_daily_loss_pct' in data:
            try:
                data['max_daily_loss_pct'] = float(data['max_daily_loss_pct'])
                if data['max_daily_loss_pct'] <= 0 or data['max_daily_loss_pct'] > 100:
                    raise ValidationError("max_daily_loss_pct must be between 0 and 100",
                                       endpoint="/protection/config",
                                       request_context=get_request_context(request))
            except (ValueError, TypeError):
                raise ValidationError("max_daily_loss_pct must be a valid number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))
        
        if 'max_total_drawdown_pct' in data:
            try:
                data['max_total_drawdown_pct'] = float(data['max_total_drawdown_pct'])
                if data['max_total_drawdown_pct'] <= 0 or data['max_total_drawdown_pct'] > 100:
                    raise ValidationError("max_total_drawdown_pct must be between 0 and 100",
                                       endpoint="/protection/config",
                                       request_context=get_request_context(request))
            except (ValueError, TypeError):
                raise ValidationError("max_total_drawdown_pct must be a valid number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'max_daily_loss_abs' in data:
            try:
                data['max_daily_loss_abs'] = float(data['max_daily_loss_abs'])
                if data['max_daily_loss_abs'] < 0:
                    raise ValidationError("max_daily_loss_abs must be 0 or greater",
                                       endpoint="/protection/config",
                                       request_context=get_request_context(request))
            except (ValueError, TypeError):
                raise ValidationError("max_daily_loss_abs must be a valid number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'max_total_drawdown_abs' in data:
            try:
                data['max_total_drawdown_abs'] = float(data['max_total_drawdown_abs'])
                if data['max_total_drawdown_abs'] < 0:
                    raise ValidationError("max_total_drawdown_abs must be 0 or greater",
                                       endpoint="/protection/config",
                                       request_context=get_request_context(request))
            except (ValueError, TypeError):
                raise ValidationError("max_total_drawdown_abs must be a valid number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'min_margin_level_pct' in data:
            try:
                data['min_margin_level_pct'] = float(data['min_margin_level_pct'])
                if data['min_margin_level_pct'] < 0:
                    raise ValidationError("min_margin_level_pct must be 0 or greater",
                                       endpoint="/protection/config",
                                       request_context=get_request_context(request))
            except (ValueError, TypeError):
                raise ValidationError("min_margin_level_pct must be a valid number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'action' in data:
            allowed_actions = ['close_all', 'notify_only', 'close_losers_only', 'close_losing', 'close_profitable']
            if data['action'] not in allowed_actions:
                raise ValidationError(f"action must be one of: {', '.join(allowed_actions)}",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'day_offset_hours' in data:
            try:
                data['day_offset_hours'] = float(data['day_offset_hours'])
            except (ValueError, TypeError):
                raise ValidationError("day_offset_hours must be a valid number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))
            if not -14 <= data['day_offset_hours'] <= 14:
                raise ValidationError("day_offset_hours must be between -14 and 14",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'heartbeat_interval' in data:
            try:
                data['heartbeat_interval'] = float(data['heartbeat_interval'])
                if data['heartbeat_interval'] < 0.01:
                    raise ValidationError("heartbeat_interval must be at least 0.01",
                                       endpoint="/protection/config",
                                       request_context=get_request_context(request))
            except (ValueError, TypeError):
                raise ValidationError("heartbeat_interval must be a valid number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'order_check_interval' in data:
            try:
                data['order_check_interval'] = float(data['order_check_interval'])
            except (ValueError, TypeError):
                raise ValidationError("order_check_interval must be a number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'ws_update_interval' in data:
            try:
                data['ws_update_interval'] = float(data['ws_update_interval'])
            except (ValueError, TypeError):
                raise ValidationError("ws_update_interval must be a number",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))

        if 'auto_reset_daily' in data:
            if not isinstance(data['auto_reset_daily'], bool):
                raise ValidationError("auto_reset_daily must be a boolean",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))
        
        if 'verbose_logging' in data:
            if not isinstance(data['verbose_logging'], bool):
                raise ValidationError("verbose_logging must be a boolean",
                                   endpoint="/protection/config",
                                   request_context=get_request_context(request))
        
        # Update configuration
        success = protection.update_config(data)
        if not success:
            return jsonify({"error": "Failed to update configuration"}), 500
        
        return jsonify({
            "message": "Configuration updated successfully",
            "config": protection.get_config()
        }), 200
    except ValidationError as e:
        return format_error_response(e, 400)
    except Exception as e:
        logger.error("update_protection_config: %s", e)
        return format_error_response(e, 500, endpoint="/protection/config", request_context=get_request_context(request))


@protection_bp.route("/protection/enable", methods=["POST"])
@require_api_key
@swag_from(enable_protection_spec)
def enable_protection():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        success = protection.start()
        if success:
            return jsonify({"message": "Protection enabled successfully"}), 200
        else:
            return jsonify({"message": "Protection is already enabled"}), 200
    except Exception as e:
        logger.error("enable_protection: %s", e)
        return format_error_response(e, 500, endpoint="/protection/enable", request_context=get_request_context(request))


@protection_bp.route("/protection/disable", methods=["POST"])
@require_api_key
@swag_from(disable_protection_spec)
def disable_protection():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        success = protection.stop()
        if success:
            return jsonify({"message": "Protection disabled successfully"}), 200
        else:
            return jsonify({"message": "Protection is already disabled"}), 200
    except Exception as e:
        logger.error("disable_protection: %s", e)
        return format_error_response(e, 500, endpoint="/protection/disable", request_context=get_request_context(request))


@protection_bp.route("/protection/status", methods=["GET"])
@require_api_key
@swag_from(get_protection_status_spec)
def get_protection_status():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        status = protection.get_equity_status()
        if "error" in status:
            return jsonify(status), 500
        
        return jsonify(status), 200
    except Exception as e:
        logger.error("get_protection_status: %s", e)
        return format_error_response(e, 500, endpoint="/protection/status", request_context=get_request_context(request))


@protection_bp.route("/protection/accounts", methods=["GET"])
@require_api_key
@swag_from(get_all_accounts_status_spec)
def get_all_accounts_status():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        status = protection.get_all_accounts_status()
        if "error" in status:
            return jsonify(status), 500
        
        return jsonify(status), 200
    except Exception as e:
        logger.error("get_all_accounts_status: %s", e)
        return format_error_response(e, 500, endpoint="/protection/accounts", request_context=get_request_context(request))


@protection_bp.route("/protection/reset_block", methods=["POST"])
@require_api_key
@swag_from(reset_account_block_spec)
def reset_account_block():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        data = request.get_json() or {}
        account_number = data.get('account_number')
        
        success = protection.reset_account_block(account_number)
        if success:
            return jsonify({"message": f"Trading block removed for account {account_number}"}), 200
        else:
            return jsonify({"message": "Account was not blocked or could not be reset"}), 200
    except Exception as e:
        logger.error("reset_account_block: %s", e)
        return format_error_response(e, 500, endpoint="/protection/reset_block", request_context=get_request_context(request))


@protection_bp.route("/protection/toggle_verbose", methods=["POST"])
@require_api_key
@swag_from(toggle_verbose_logging_spec)
def toggle_verbose_logging():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        success = protection.toggle_verbose_logging()
        if success:
            return jsonify({
                "message": f"Verbose logging {'enabled' if protection.verbose_logging else 'disabled'}",
                "verbose_logging": protection.verbose_logging
            }), 200
        else:
            return jsonify({"error": "Failed to toggle verbose logging"}), 500
    except Exception as e:
        logger.error("toggle_verbose_logging: %s", e)
        return format_error_response(e, 500, endpoint="/protection/toggle_verbose", request_context=get_request_context(request))


@protection_bp.route("/protection/close/all", methods=["POST"])
@require_api_key
@swag_from(manual_close_all_spec)
def manual_close_all():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        result = protection.manual_close_all()
        return jsonify({"message": "Full liquidation triggered", "result": result}), 200
    except Exception as e:
        logger.error("manual_close_all: %s", e)
        return format_error_response(e, 500, endpoint="/protection/close/all", request_context=get_request_context(request))


@protection_bp.route("/protection/close/profitable", methods=["POST"])
@require_api_key
@swag_from(manual_close_profitable_spec)
def manual_close_profitable():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        result = protection.manual_close_profitable()
        return jsonify({"message": "Profitable positions closed", "result": result}), 200
    except Exception as e:
        logger.error("manual_close_profitable: %s", e)
        return format_error_response(e, 500, endpoint="/protection/close/profitable", request_context=get_request_context(request))


@protection_bp.route("/protection/close/losing", methods=["POST"])
@require_api_key
@swag_from(manual_close_losing_spec)
def manual_close_losing():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        result = protection.manual_close_losing()
        return jsonify({"message": "Losing positions closed", "result": result}), 200
    except Exception as e:
        logger.error("manual_close_losing: %s", e)
        return format_error_response(e, 500, endpoint="/protection/close/losing", request_context=get_request_context(request))


@protection_bp.route("/protection/close/symbol", methods=["POST"])
@require_api_key
@swag_from(manual_close_symbol_spec)
def manual_close_symbol():
    try:
        protection = get_protection_service()
        if protection is None:
            return jsonify({"error": "Protection service not initialized"}), 500
        
        data = request.get_json() or {}
        symbol = data.get('symbol')
        if not symbol:
            return jsonify({"error": "Symbol is required"}), 400
            
        result = protection.manual_close_symbol(symbol)
        return jsonify({"message": f"Positions for {symbol} closed", "result": result}), 200
    except Exception as e:
        logger.error("manual_close_symbol: %s", e)
        return format_error_response(e, 500, endpoint="/protection/close/symbol", request_context=get_request_context(request))

