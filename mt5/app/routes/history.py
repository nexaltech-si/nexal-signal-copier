from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import pandas as pd
import pytz
import logging
from datetime import datetime
from flasgger import swag_from
from lib import get_deal_from_ticket, get_order_from_ticket, MT5_TIMEZONE, parse_iso_datetime, mt5_read_failed
from middleware.auth import require_api_key
from errors import ValidationError, DataError
from utils.error_handler import format_error_response, get_request_context
from utils.validation_schemas import validate_request, HistoryDealsGetSchema, HistoryOrdersGetSchema, DealFromTicketSchema, OrderFromTicketSchema, AccountStatsSchema
from swagger_specs import (
    history_deals_spec, history_orders_spec, get_deal_from_ticket_spec,
    get_order_from_ticket_spec, account_stats_spec
)

history_bp = Blueprint("history", __name__)
logger = logging.getLogger(__name__)




@history_bp.route("/history_deals_get")
@history_bp.route("/history")
@require_api_key
@swag_from(history_deals_spec)
def history_deals_get():
    try:
        data = {
            "from_date": request.args.get("from_date"),
            "to_date": request.args.get("to_date"),
            "position": request.args.get("position", type=int),
            "symbol": request.args.get("symbol"),
            "magic": request.args.get("magic", type=int)
        }
        validated = validate_request(HistoryDealsGetSchema(), data, endpoint="/history_deals_get")

        from_ts = int(parse_iso_datetime(validated["from_date"]).timestamp())
        to_ts   = int(parse_iso_datetime(validated["to_date"]).timestamp())

        kwargs = {"position": validated["position"]} if validated["position"] is not None else {}
        deals  = mt5.history_deals_get(from_ts, to_ts, **kwargs)
        if mt5_read_failed(deals):
            logger.error("history_deals_get: MT5 failed: %s", mt5.last_error())
            return jsonify({"error": "MT5 read failed", "detail": str(mt5.last_error())}), 503
        if deals is None:
            return jsonify([]), 200

        # ── Filter to isolate the correct trade's deals ──────────────────
        if validated["position"] is not None and deals:
            original_count = len(deals)
            deals = [d for d in deals if d.position_id == validated["position"]]
            
            if len(deals) < original_count:
                logger.info(
                    "history_deals_get: filtered %d→%d deals for position %d (strict position_id match)",
                    original_count, len(deals), validated["position"],
                )

        result = []
        for d in deals:
            rec = d._asdict()
            rec["time"] = datetime.fromtimestamp(rec["time"], tz=MT5_TIMEZONE).isoformat()
            result.append(rec)
        return jsonify(result)
    except (ValidationError, ValueError) as e:
        return format_error_response(e, 400)
    except Exception as e:
        logger.error("history_deals_get: %s", e)
        return format_error_response(e, 500, endpoint="/history_deals_get", request_context=get_request_context(request))


@history_bp.route("/history_orders_get")
@require_api_key
@swag_from(history_orders_spec)
def history_orders_get():
    try:
        data = {
            "ticket": request.args.get("ticket", type=int),
            "from_date": request.args.get("from_date"),
            "to_date": request.args.get("to_date")
        }
        validated = validate_request(HistoryOrdersGetSchema(), data, endpoint="/history_orders_get")

        if validated["ticket"] is not None:
            orders = mt5.history_orders_get(ticket=validated["ticket"])
        elif validated["from_date"] and validated["to_date"]:
            from_ts = int(parse_iso_datetime(validated["from_date"]).timestamp())
            to_ts   = int(parse_iso_datetime(validated["to_date"]).timestamp())
            orders  = mt5.history_orders_get(from_ts, to_ts)
        else:
            raise ValidationError("Provide ticket or from_date + to_date", endpoint="/history_orders_get", request_context=get_request_context(request))

        if mt5_read_failed(orders):
            logger.error("history_orders_get: MT5 failed: %s", mt5.last_error())
            return jsonify({"error": "MT5 read failed", "detail": str(mt5.last_error())}), 503
        if orders is None:
            return jsonify({"orders": []}), 200

        result = []
        for o in orders:
            rec = o._asdict()
            for col in ["time_setup", "time_done"]:
                if col in rec and rec[col]:
                    rec[col] = datetime.fromtimestamp(rec[col], tz=MT5_TIMEZONE).isoformat()
            result.append(rec)
        return jsonify({"orders": result})
    except (ValidationError, ValueError) as e:
        return format_error_response(e, 400)
    except Exception as e:
        logger.error("history_orders_get: %s", e)
        return format_error_response(e, 500, endpoint="/history_orders_get", request_context=get_request_context(request))


@history_bp.route("/get_deal_from_ticket")
@require_api_key
@swag_from(get_deal_from_ticket_spec)
def get_deal_ticket():
    try:
        data = {"ticket": request.args.get("ticket", type=int)}
        validated = validate_request(DealFromTicketSchema(), data, endpoint="/get_deal_from_ticket")
        
        deal = get_deal_from_ticket(validated["ticket"])
        if deal is None:
            raise DataError("No deal found", endpoint="/get_deal_from_ticket", request_context=get_request_context(request))
        return jsonify(deal)
    except (ValidationError, DataError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 404)
    except Exception as e:
        logger.error("get_deal_from_ticket: %s", e)
        return format_error_response(e, 500, endpoint="/get_deal_from_ticket", request_context=get_request_context(request))


@history_bp.route("/get_order_from_ticket")
@require_api_key
@swag_from(get_order_from_ticket_spec)
def get_order_ticket():
    try:
        data = {"ticket": request.args.get("ticket", type=int)}
        validated = validate_request(OrderFromTicketSchema(), data, endpoint="/get_order_from_ticket")
        
        order = get_order_from_ticket(validated["ticket"])
        if order is None:
            raise DataError("No order found", endpoint="/get_order_from_ticket", request_context=get_request_context(request))
        return jsonify(order)
    except (ValidationError, DataError) as e:
        return format_error_response(e, 400 if isinstance(e, ValidationError) else 404)
    except Exception as e:
        logger.error("get_order_from_ticket: %s", e)
        return format_error_response(e, 500, endpoint="/get_order_from_ticket", request_context=get_request_context(request))


@history_bp.route("/account_stats")
@require_api_key
@swag_from(account_stats_spec)
def account_stats():
    try:
        data = {
            "from_date": request.args.get("from_date"),
            "to_date": request.args.get("to_date")
        }
        validated = validate_request(AccountStatsSchema(), data, endpoint="/account_stats")

        from_ts = int(parse_iso_datetime(validated["from_date"]).timestamp())
        to_ts   = int(parse_iso_datetime(validated["to_date"]).timestamp())
        deals   = mt5.history_deals_get(from_ts, to_ts)

        if not deals:
            return jsonify({"total_trades": 0, "message": "No deals in range"}), 200

        df = pd.DataFrame([d._asdict() for d in deals])
        if "type" in df.columns:   # trades only: balance/credit/charge deals are not trades
            df = df[df["type"].isin([0, 1])]
        # Only count OUT deals (closing deals): DEAL_ENTRY_IN=0, DEAL_ENTRY_OUT=1, DEAL_ENTRY_INOUT=2
        closed = df[df["entry"] == 1] if "entry" in df.columns else df

        wins   = closed[closed["profit"] > 0]
        losses = closed[closed["profit"] < 0]
        n      = len(closed)

        gross_profit = float(wins["profit"].sum())   if not wins.empty   else 0.0
        gross_loss   = float(losses["profit"].sum()) if not losses.empty else 0.0
        profit_factor = round(abs(gross_profit / gross_loss), 4) if gross_loss != 0 else None

        return jsonify({
            "total_trades":     n,
            "wins":             len(wins),
            "losses":           len(losses),
            "win_rate":         round(len(wins) / n * 100, 2) if n else 0,
            "total_profit":     float(closed["profit"].sum()),
            "gross_profit":     gross_profit,
            "gross_loss":       gross_loss,
            "profit_factor":    profit_factor,
            "avg_win":          round(gross_profit / len(wins), 5)   if not wins.empty   else 0,
            "avg_loss":         round(gross_loss   / len(losses), 5) if not losses.empty else 0,
            "total_commission": float(closed["commission"].sum()) if "commission" in closed.columns else 0,
            "total_swap":       float(closed["swap"].sum())       if "swap"       in closed.columns else 0,
        })
    except (ValidationError, ValueError) as e:
        return format_error_response(e, 400)
    except Exception as e:
        logger.error("account_stats: %s", e)
        return format_error_response(e, 500, endpoint="/account_stats", request_context=get_request_context(request))

