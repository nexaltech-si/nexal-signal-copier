from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import logging
from flasgger import swag_from
from lib import resolve_filling_mode, close_all_orders, normalize_price
from middleware.auth import require_api_key, require_trading_not_blocked
from errors import ValidationError, OrderError, MT5ConnectionError
from utils.error_handler import format_error_response, handle_mt5_error, get_request_context
from utils.validation_schemas import validate_request, MarketOrderSchema, PendingOrderSchema, CancelOrderSchema, ModifyOrderSchema, CloseAllOrdersSchema
from swagger_specs import (
    send_market_order_spec, send_pending_order_spec, cancel_order_spec,
    modify_order_spec, close_all_orders_spec
)

order_bp = Blueprint("order", __name__)
logger = logging.getLogger(__name__)

PENDING_TYPE_MAP = {
    "BUY_LIMIT":       mt5.ORDER_TYPE_BUY_LIMIT,
    "SELL_LIMIT":      mt5.ORDER_TYPE_SELL_LIMIT,
    "BUY_STOP":        mt5.ORDER_TYPE_BUY_STOP,
    "SELL_STOP":       mt5.ORDER_TYPE_SELL_STOP,
    "BUY_STOP_LIMIT":  mt5.ORDER_TYPE_BUY_STOP_LIMIT,
    "SELL_STOP_LIMIT": mt5.ORDER_TYPE_SELL_STOP_LIMIT,
}


def _order_error(result):
    ec, es = mt5.last_error()
    error = OrderError(
        message="Order failed: {}".format(result.comment if result else "no result"),
        mt5_error=es,
        retcode=result.retcode if result else None
    )
    return format_error_response(error, 400)


@order_bp.route("/order", methods=["POST"])
@require_api_key
@require_trading_not_blocked
@swag_from(send_market_order_spec)
def send_market_order():
    try:
        data = request.get_json()
        if not data:
            raise ValidationError("JSON body required", endpoint="/order", request_context=get_request_context(request))
        
        # Validate input using schema
        validated = validate_request(MarketOrderSchema(), data, endpoint="/order")

        raw_type = str(validated["type"]).upper()
        if raw_type in ("BUY", "0"):
            order_type = mt5.ORDER_TYPE_BUY
        elif raw_type in ("SELL", "1"):
            order_type = mt5.ORDER_TYPE_SELL
        else:
            raise ValidationError(f"Invalid type: {raw_type}", field="type", endpoint="/order", request_context=get_request_context(request))

        symbol = validated["symbol"]
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5ConnectionError("Failed to get price for symbol", endpoint="/order", request_context=get_request_context(request))

        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        filling = resolve_filling_mode(validated.get("type_filling"), symbol)

        req = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       float(validated["volume"]),
            "type":         order_type,
            "price":        price,
            "deviation":    int(validated.get("deviation", 20)),
            "magic":        int(validated.get("magic", 0)),
            "comment":      validated.get("comment", ""),
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        if validated.get("sl") is not None:
            req["sl"] = normalize_price(symbol, validated["sl"])
        if validated.get("tp") is not None:
            req["tp"] = normalize_price(symbol, validated["tp"])

        result = mt5.order_send(req)
        handle_mt5_error(result, "Market order", endpoint="/order", request_context=get_request_context(request))

        return jsonify({"message": "Order executed", "result": result._asdict()})

    except (ValidationError, OrderError, MT5ConnectionError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 500)
    except Exception as e:
        logger.error("send_market_order: %s", e)
        return format_error_response(e, 500, endpoint="/order", request_context=get_request_context(request))


@order_bp.route("/limit_order", methods=["POST"])
@require_api_key
@require_trading_not_blocked
@swag_from(send_pending_order_spec)
def send_pending_order():
    try:
        data = request.get_json()
        if not data:
            raise ValidationError("JSON body required", endpoint="/limit_order", request_context=get_request_context(request))
        for f in ["symbol", "volume", "type", "price"]:
            if f not in data:
                raise ValidationError(f"Missing field: {f}", field=f, endpoint="/limit_order", request_context=get_request_context(request))

        raw_type = str(data["type"]).upper()
        if raw_type not in PENDING_TYPE_MAP:
            raise ValidationError(f"Invalid type: {raw_type}. Valid: {list(PENDING_TYPE_MAP.keys())}", field="type", endpoint="/limit_order", request_context=get_request_context(request))

        symbol   = data["symbol"]
        filling  = resolve_filling_mode(data.get("type_filling"), symbol)

        req = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       symbol,
            "volume":       float(data["volume"]),
            "type":         PENDING_TYPE_MAP[raw_type],
            "price":        normalize_price(symbol, data["price"]),
            "deviation":    int(data.get("deviation", 20)),
            "magic":        int(data.get("magic", 0)),
            "comment":      data.get("comment", ""),
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        if data.get("sl") is not None:
            req["sl"] = normalize_price(symbol, data["sl"])
        if data.get("tp") is not None:
            req["tp"] = normalize_price(symbol, data["tp"])
        # stoplimit_price is required for BUY_STOP_LIMIT / SELL_STOP_LIMIT
        if data.get("stoplimit_price") is not None:
            req["stoplimit"] = normalize_price(symbol, data["stoplimit_price"])
        if "expiration" in data:
            from datetime import datetime
            import pytz
            exp = datetime.fromisoformat(data["expiration"].replace("Z", "+00:00"))
            req["type_time"] = mt5.ORDER_TIME_SPECIFIED
            req["expiration"] = int(exp.timestamp())

        result = mt5.order_send(req)
        handle_mt5_error(result, "Pending order", endpoint="/limit_order", request_context=get_request_context(request))

        return jsonify({"message": "Pending order placed", "result": result._asdict()})

    except (ValidationError, OrderError, MT5ConnectionError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 500)
    except Exception as e:
        logger.error("send_pending_order: %s", e)
        return format_error_response(e, 500, endpoint="/limit_order", request_context=get_request_context(request))


@order_bp.route("/cancel_order", methods=["POST"])
@require_api_key
@swag_from(cancel_order_spec)
def cancel_order():
    try:
        data = request.get_json()
        if not data or "ticket" not in data:
            raise ValidationError("ticket required", field="ticket", endpoint="/cancel_order", request_context=get_request_context(request))

        req = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order":  int(data["ticket"]),
        }
        result = mt5.order_send(req)
        handle_mt5_error(result, "Cancel order", endpoint="/cancel_order", request_context=get_request_context(request))

        return jsonify({"message": "Order cancelled", "result": result._asdict()})

    except (ValidationError, OrderError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 500)
    except Exception as e:
        logger.error("cancel_order: %s", e)
        return format_error_response(e, 500, endpoint="/cancel_order", request_context=get_request_context(request))


@order_bp.route("/modify_order", methods=["POST"])
@require_api_key
@swag_from(modify_order_spec)
def modify_order():
    try:
        data = request.get_json()
        if not data or "ticket" not in data:
            raise ValidationError("ticket required", field="ticket", endpoint="/modify_order", request_context=get_request_context(request))

        ticket = int(data["ticket"])
        existing = mt5.orders_get(ticket=ticket)
        if not existing:
            raise ValidationError(f"Order {ticket} not found (already filled or cancelled)", field="ticket", endpoint="/modify_order", request_context=get_request_context(request))
        cur = existing[0]

        # MODIFY replaces the whole order: anything omitted would be reset (price -> 0, SL/TP removed).
        # Fall back to the order's current values for every field the caller did not send.
        req = {
            "action": mt5.TRADE_ACTION_MODIFY,
            "order":  ticket,
            "price":  normalize_price(cur.symbol, data["price"] if data.get("price") is not None else cur.price_open),
            "sl":     normalize_price(cur.symbol, data["sl"] if data.get("sl") is not None else cur.sl),
            "tp":     normalize_price(cur.symbol, data["tp"] if data.get("tp") is not None else cur.tp),
        }
        if data.get("stoplimit_price") is not None:
            req["stoplimit"] = normalize_price(cur.symbol, data["stoplimit_price"])
        if "expiration" in data:
            from datetime import datetime
            exp = datetime.fromisoformat(data["expiration"].replace("Z", "+00:00"))
            req["type_time"] = mt5.ORDER_TIME_SPECIFIED
            req["expiration"] = int(exp.timestamp())

        result = mt5.order_send(req)
        handle_mt5_error(result, "Modify order", endpoint="/modify_order", request_context=get_request_context(request))

        return jsonify({"message": "Order modified", "result": result._asdict()})

    except (ValidationError, OrderError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 500)
    except Exception as e:
        logger.error("modify_order: %s", e)
        return format_error_response(e, 500, endpoint="/modify_order", request_context=get_request_context(request))


@order_bp.route("/close_all_orders", methods=["POST"])
@require_api_key
@swag_from(close_all_orders_spec)
def close_all_orders_endpoint():
    try:
        data = request.get_json() or {}
        results = close_all_orders(
            magic=data.get("magic"),
            symbol=data.get("symbol"),
            order_type=data.get("order_type")
        )
        if not results:
            return jsonify({"message": "No orders closed", "count": 0}), 200
        return jsonify({
            "message": f"Cancelled {len(results)} orders",
            "count": len(results),
            "results": [r._asdict() for r in results],
        })
    except Exception as e:
        logger.error("close_all_orders: %s", e)
        return format_error_response(e, 500, endpoint="/close_all_orders", request_context=get_request_context(request))

