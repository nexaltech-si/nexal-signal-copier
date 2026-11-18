from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import logging
from flasgger import swag_from
from lib import (
    MT5ReadError, get_positions_strict, normalize_price, mt5_read_failed,
    close_position, close_all_positions, get_positions, serialize_positions_df,
    close_all_profitable_positions, close_losing_positions, close_positions_by_symbol
)
from middleware.auth import require_api_key
from errors import ValidationError, OrderError, MT5ConnectionError
from utils.error_handler import format_error_response, handle_mt5_error, get_request_context
from utils.validation_schemas import validate_request, ClosePositionSchema, ModifySLTPSchema, CloseAllPositionsSchema
from swagger_specs import (
    positions_total_spec, get_positions_spec, get_orders_spec,
    close_position_spec, close_partial_spec, close_all_positions_spec,
    modify_sl_tp_spec, close_profitable_spec, close_losing_spec, close_symbol_spec
)

position_bp = Blueprint("position", __name__)
logger = logging.getLogger(__name__)


@position_bp.route("/positions_total")
@require_api_key
@swag_from(positions_total_spec)
def positions_total():
    try:
        total = mt5.positions_total()
        if total is None:
            raise MT5ConnectionError("Failed to get positions total", endpoint="/positions_total", request_context=get_request_context(request))
        return jsonify({"total": total})
    except MT5ConnectionError as e:
        return format_error_response(e, 500)
    except Exception as e:
        logger.error("positions_total: %s", e)
        return format_error_response(e, 500, endpoint="/positions_total", request_context=get_request_context(request))


@position_bp.route("/get_positions")
@require_api_key
@swag_from(get_positions_spec)
def get_positions_endpoint():
    try:
        magic = request.args.get("magic", type=int)
        df = get_positions_strict(magic)
        return jsonify(serialize_positions_df(df)), 200
    except MT5ReadError as e:
        # 503, not an empty 200: a failed read must never look like a flat account
        logger.error("get_positions: %s", e)
        return jsonify({"error": "MT5 read failed", "detail": str(e)}), 503
    except Exception as e:
        logger.error("get_positions: %s", e)
        return format_error_response(e, 500, endpoint="/get_positions", request_context=get_request_context(request))


@position_bp.route("/get_orders")
@require_api_key
@swag_from(get_orders_spec)
def get_orders():
    try:
        magic  = request.args.get("magic", type=int)
        orders = mt5.orders_get()
        if mt5_read_failed(orders):
            # orders_get() returns None on ERROR (last_error != success); a flat account answers () / success
            logger.error("get_orders: orders_get() failed: %s", mt5.last_error())
            return jsonify({"error": "MT5 read failed", "detail": str(mt5.last_error())}), 503
        if orders is None:
            return jsonify({"orders": []}), 200
        result = [o._asdict() for o in orders if magic is None or o.magic == magic]
        return jsonify({"orders": result}), 200
    except Exception as e:
        logger.error("get_orders: %s", e)
        return format_error_response(e, 500, endpoint="/get_orders", request_context=get_request_context(request))


@position_bp.route("/close_position", methods=["POST"])
@require_api_key
@swag_from(close_position_spec)
def close_position_endpoint():
    try:
        data = request.get_json()
        if not data:
            raise ValidationError("JSON body required", endpoint="/close_position", request_context=get_request_context(request))
        
        validated = validate_request(ClosePositionSchema(), data, endpoint="/close_position")
        result = close_position(validated["position"])
        if result is None:
            raise OrderError("Failed to close position", endpoint="/close_position", request_context=get_request_context(request))
        return jsonify({"message": "Position closed", "result": result._asdict()})
    except (ValidationError, OrderError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 500)
    except Exception as e:
        logger.error("close_position: %s", e)
        return format_error_response(e, 500, endpoint="/close_position", request_context=get_request_context(request))


@position_bp.route("/close_partial", methods=["POST"])
@require_api_key
@swag_from(close_partial_spec)
def close_partial():
    try:
        data = request.get_json()
        if not data:
            raise ValidationError("JSON body required", endpoint="/close_partial", request_context=get_request_context(request))
        
        validated = validate_request(ClosePositionSchema(), data, endpoint="/close_partial")
        vol = validated["volume"]
        pos = validated["position"]
        if vol <= 0 or vol > float(pos.get("volume", 0)):
            raise ValidationError("Invalid partial volume", field="volume", endpoint="/close_partial", request_context=get_request_context(request))
        result = close_position(pos, volume=vol)
        if result is None:
            raise OrderError("Failed to partially close position", endpoint="/close_partial", request_context=get_request_context(request))
        return jsonify({"message": f"Closed {vol} lots", "result": result._asdict()})
    except (ValidationError, OrderError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 500)
    except Exception as e:
        logger.error("close_partial: %s", e)
        return format_error_response(e, 500, endpoint="/close_partial", request_context=get_request_context(request))


@position_bp.route("/close_all_positions", methods=["POST"])
@require_api_key
@swag_from(close_all_positions_spec)
def close_all_positions_endpoint():
    try:
        try:
            data = request.get_json() or {}
        except Exception:
            data = {}
        validated = validate_request(CloseAllPositionsSchema(), data, endpoint="/close_all_positions")
        results = close_all_positions(
            order_type=validated.get("order_type", "all"),
            magic=validated.get("magic"),
        )
        if not results:
            return jsonify({"message": "No positions closed", "count": 0}), 200
        return jsonify({
            "message": f"Closed {len(results)} positions",
            "count": len(results),
            "results": [r._asdict() for r in results],
        })
    except Exception as e:
        logger.error("close_all_positions: %s", e)
        return format_error_response(e, 500, endpoint="/close_all_positions", request_context=get_request_context(request))


@position_bp.route("/close_profitable", methods=["POST"])
@require_api_key
@swag_from(close_profitable_spec)
def close_profitable_endpoint():
    try:
        data = request.get_json() or {}
        magic = data.get("magic")
        results = close_all_profitable_positions(magic=magic)
        return jsonify({
            "message": f"Closed {len(results)} profitable positions",
            "count": len(results),
            "results": [r._asdict() for r in results if r]
        }), 200
    except Exception as e:
        logger.error("close_profitable: %s", e)
        return format_error_response(e, 500, endpoint="/close_profitable", request_context=get_request_context(request))


@position_bp.route("/close_losing", methods=["POST"])
@require_api_key
@swag_from(close_losing_spec)
def close_losing_endpoint():
    try:
        data = request.get_json() or {}
        magic = data.get("magic")
        results = close_losing_positions(magic=magic)
        return jsonify({
            "message": f"Closed {len(results)} losing positions",
            "count": len(results),
            "results": [r._asdict() for r in results if r]
        }), 200
    except Exception as e:
        logger.error("close_losing: %s", e)
        return format_error_response(e, 500, endpoint="/close_losing", request_context=get_request_context(request))


@position_bp.route("/close_symbol", methods=["POST"])
@require_api_key
@swag_from(close_symbol_spec)
def close_symbol_endpoint():
    try:
        data = request.get_json() or {}
        symbol = data.get("symbol")
        if not symbol:
            return jsonify({"error": "Symbol is required"}), 400
        
        magic = data.get("magic")
        results = close_positions_by_symbol(symbol, magic=magic)
        return jsonify({
            "message": f"Closed {len(results)} positions for {symbol}",
            "count": len(results),
            "results": [r._asdict() for r in results if r]
        }), 200
    except Exception as e:
        logger.error("close_symbol: %s", e)
        return format_error_response(e, 500, endpoint="/close_symbol", request_context=get_request_context(request))


@position_bp.route("/modify_sl_tp", methods=["POST"])
@require_api_key
@swag_from(modify_sl_tp_spec)
def modify_sl_tp():
    try:
        data = request.get_json()
        if not data:
            raise ValidationError("JSON body required", endpoint="/modify_sl_tp", request_context=get_request_context(request))
        
        validated = validate_request(ModifySLTPSchema(), data, endpoint="/modify_sl_tp")

        # Look up symbol for the position so we can set the correct price
        pos_ticket = int(validated["position"])
        positions = mt5.positions_get(ticket=pos_ticket)
        if not positions:
            logger.warning("Attempted to modify SL/TP for non-existent position %s", pos_ticket)
            raise ValidationError(f"Position {pos_ticket} not found", endpoint="/modify_sl_tp", request_context=get_request_context(request))
        pos = positions[0]

        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": pos_ticket,
            "sl": normalize_price(pos.symbol, validated.get("sl", pos.sl)),
            "tp": normalize_price(pos.symbol, validated.get("tp", pos.tp)),
        }
        result = mt5.order_send(req)
        handle_mt5_error(result, "Modify SL/TP", endpoint="/modify_sl_tp", request_context=get_request_context(request))

        return jsonify({"message": "SL/TP updated", "result": result._asdict()})
    except (ValidationError, OrderError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 500)
    except Exception as e:
        logger.error("modify_sl_tp: %s", e)
        return format_error_response(e, 500, endpoint="/modify_sl_tp", request_context=get_request_context(request))

