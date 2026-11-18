from flask import Blueprint, jsonify, request
import MetaTrader5 as mt5
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import pytz
from flasgger import swag_from
from lib import MT5_TIMEZONE, parse_iso_datetime, BROKER_TIMEZONE_OFFSET, MT5ReadError, mt5_read_failed
from middleware.auth import require_api_key
from errors import ValidationError, DataError
from utils.error_handler import format_error_response, get_request_context
from swagger_specs import (
    trade_lifecycle_spec, trade_status_spec, batch_trade_status_spec,
    trade_search_spec
)

trade_lifecycle_bp = Blueprint("trade_lifecycle", __name__)
logger = logging.getLogger(__name__)


def _serialize_timestamp(ts: int, is_msc: bool = False) -> str:
    divisor = 1000 if is_msc else 1
    try:
        return datetime.fromtimestamp(ts / divisor, tz=MT5_TIMEZONE).isoformat()
    except Exception:
        return None


def _get_order_state_label(state: int) -> str:
    states = {
        0: "STARTED",
        1: "PLACED",
        2: "CANCELED",
        3: "PARTIAL",
        4: "FILLED",
        5: "REJECTED",
        6: "EXPIRED",
        7: "REQUEST_ADD",
        8: "REQUEST_MODIFY",
        9: "REQUEST_CANCEL",
    }
    return states.get(state, f"UNKNOWN_{state}")


def _get_deal_entry_label(entry: int) -> str:
    entries = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}
    return entries.get(entry, f"UNKNOWN_{entry}")


def _get_order_type_label(order_type: int) -> str:
    types = {
        0: "BUY",
        1: "SELL",
        2: "BUY_LIMIT",
        3: "SELL_LIMIT",
        4: "BUY_STOP",
        5: "SELL_STOP",
        6: "BUY_STOP_LIMIT",
        7: "SELL_STOP_LIMIT",
        8: "CLOSE_BY",
    }
    return types.get(order_type, f"UNKNOWN_{order_type}")


def _fetch_order_by_ticket(ticket: int) -> Optional[Dict[str, Any]]:
    try:
        orders = mt5.history_orders_get(ticket=ticket)
        if not orders:
            return None
        
        order = orders[0]
        return {
            "ticket": order.ticket,
            "time_setup": _serialize_timestamp(order.time_setup),
            "time_setup_msc": _serialize_timestamp(order.time_setup_msc, is_msc=True),
            "time_done": _serialize_timestamp(order.time_done) if order.time_done else None,
            "time_done_msc": _serialize_timestamp(order.time_done_msc, is_msc=True) if order.time_done_msc else None,
            "time_expiration": _serialize_timestamp(order.time_expiration) if order.time_expiration else None,
            "type": _get_order_type_label(order.type),
            "type_raw": order.type,
            "state": _get_order_state_label(order.state),
            "state_raw": order.state,
            "type_filling": order.type_filling,
            "type_time": order.type_time,
            "magic": order.magic,
            "position_id": order.position_id,
            "position_by_id": order.position_by_id,
            "reason": order.reason,
            "volume_initial": float(order.volume_initial),
            "volume_current": float(order.volume_current),
            "price_open": float(order.price_open),
            "sl": float(order.sl),
            "tp": float(order.tp),
            "price_current": float(order.price_current),
            "price_stoplimit": float(order.price_stoplimit),
            "symbol": order.symbol,
            "comment": order.comment,
            "external_id": order.external_id,
        }
    except Exception as e:
        logger.error("_fetch_order_by_ticket error for %d: %s", ticket, e)
        return None


def _fetch_deals_by_ticket(ticket: int, from_date: datetime, to_date: datetime) -> List[Dict[str, Any]]:
    try:
        from_ts = int(from_date.timestamp())
        to_ts = int(to_date.timestamp())
        
        deals = mt5.history_deals_get(from_ts, to_ts, position=ticket)
        if not deals:
            return []
        
        deals = [d for d in deals if d.position_id == ticket]
        if not deals:
            return []
        
        result = []
        for deal in deals:
            result.append({
                "ticket": deal.ticket,
                "order": deal.order,
                "time": _serialize_timestamp(deal.time),
                "time_msc": _serialize_timestamp(deal.time_msc, is_msc=True),
                "type": _get_order_type_label(deal.type),
                "type_raw": deal.type,
                "entry": _get_deal_entry_label(deal.entry),
                "entry_raw": deal.entry,
                "magic": deal.magic,
                "position_id": deal.position_id,
                "reason": deal.reason,
                "volume": float(deal.volume),
                "price": float(deal.price),
                "commission": float(deal.commission),
                "swap": float(deal.swap),
                "profit": float(deal.profit),
                "fee": float(deal.fee),
                "symbol": deal.symbol,
                "comment": deal.comment,
                "external_id": deal.external_id,
            })
        
        return result
    except Exception as e:
        logger.error("_fetch_deals_by_ticket error for %d: %s", ticket, e)
        return []


def _fetch_position_by_ticket(ticket: int) -> Optional[Dict[str, Any]]:
    """The open position, or None when it is not open. RAISES MT5ReadError when MT5 fails to answer:
    swallowing that made a still-open (partially closed) position look closed."""
    try:
        positions = mt5.positions_get(ticket=ticket)
        if mt5_read_failed(positions):
            raise MT5ReadError("positions_get(ticket=%s) failed: %s" % (ticket, mt5.last_error()))
        if not positions:
            return None
        
        pos = positions[0]
        return {
            "ticket": pos.ticket,
            "time": _serialize_timestamp(pos.time),
            "time_msc": _serialize_timestamp(pos.time_msc, is_msc=True),
            "time_update": _serialize_timestamp(pos.time_update),
            "time_update_msc": _serialize_timestamp(pos.time_update_msc, is_msc=True),
            "type": _get_order_type_label(pos.type),
            "type_raw": pos.type,
            "magic": pos.magic,
            "identifier": pos.identifier,
            "reason": pos.reason,
            "volume": float(pos.volume),
            "price_open": float(pos.price_open),
            "sl": float(pos.sl),
            "tp": float(pos.tp),
            "price_current": float(pos.price_current),
            "swap": float(pos.swap),
            "profit": float(pos.profit),
            "symbol": pos.symbol,
            "comment": pos.comment,
            "external_id": pos.external_id,
        }
    except MT5ReadError:
        raise
    except Exception as e:
        logger.error("_fetch_position_by_ticket error for %d: %s", ticket, e)
        raise MT5ReadError(str(e)) from e


def _check_pending_order(ticket: int) -> Optional[Dict[str, Any]]:
    """The pending order, or None when there is none. RAISES MT5ReadError when MT5 fails to answer."""
    try:
        orders = mt5.orders_get(ticket=ticket)
        if mt5_read_failed(orders):
            raise MT5ReadError("orders_get(ticket=%s) failed: %s" % (ticket, mt5.last_error()))
        if not orders:
            return None
        
        order = orders[0]
        return {
            "ticket": order.ticket,
            "time_setup": _serialize_timestamp(order.time_setup),
            "time_setup_msc": _serialize_timestamp(order.time_setup_msc, is_msc=True),
            "time_expiration": _serialize_timestamp(order.time_expiration) if order.time_expiration else None,
            "type": _get_order_type_label(order.type),
            "type_raw": order.type,
            "state": _get_order_state_label(order.state),
            "state_raw": order.state,
            "type_filling": order.type_filling,
            "type_time": order.type_time,
            "magic": order.magic,
            "position_id": order.position_id,
            "position_by_id": order.position_by_id,
            "reason": order.reason,
            "volume_initial": float(order.volume_initial),
            "volume_current": float(order.volume_current),
            "price_open": float(order.price_open),
            "sl": float(order.sl),
            "tp": float(order.tp),
            "price_current": float(order.price_current),
            "price_stoplimit": float(order.price_stoplimit),
            "symbol": order.symbol,
            "comment": order.comment,
            "external_id": order.external_id,
        }
    except MT5ReadError:
        raise
    except Exception as e:
        logger.error("_check_pending_order error for %d: %s", ticket, e)
        raise MT5ReadError(str(e)) from e


def _determine_trade_status(
    pending_order: Optional[Dict],
    position: Optional[Dict],
    deals: List[Dict],
    order_history: Optional[Dict]
) -> str:
    if pending_order:
        return "PENDING"
    if position:
        return "RUNNING"
    if deals:
        net_pnl = sum(d.get("profit", 0.0) + d.get("commission", 0.0) + d.get("swap", 0.0) for d in deals)
        if net_pnl > 0.01:
            return "CLOSED_PROFIT"
        elif net_pnl < -0.01:
            return "CLOSED_LOSS"
        else:
            return "CLOSED_BREAKEVEN"
    if order_history:
        state = order_history.get("state", "")
        if state == "CANCELED":
            return "CANCELED"
        elif state == "EXPIRED":
            return "EXPIRED"
        elif state == "REJECTED":
            return "REJECTED"
    return "UNKNOWN"


@trade_lifecycle_bp.route("/trade_lifecycle", methods=["GET"])
@require_api_key
@swag_from(trade_lifecycle_spec)
def get_trade_lifecycle():
    try:
        ticket = request.args.get("ticket", type=int)
        if not ticket:
            raise ValidationError("ticket required", field="ticket", endpoint="/trade_lifecycle", request_context=get_request_context(request))
        
        days_back = request.args.get("days_back", type=int, default=30)
        to_date = datetime.now(MT5_TIMEZONE) + timedelta(hours=BROKER_TIMEZONE_OFFSET)
        from_date = to_date - timedelta(days=days_back)
        
        pending_order = _check_pending_order(ticket)
        position = _fetch_position_by_ticket(ticket)
        order_history = _fetch_order_by_ticket(ticket)
        deals = _fetch_deals_by_ticket(ticket, from_date, to_date)
        
        status = _determine_trade_status(pending_order, position, deals, order_history)
        
        summary = {
            "ticket": ticket,
            "status": status,
            "total_deals": len(deals),
            "total_profit": sum(d.get("profit", 0.0) for d in deals),
            "total_commission": sum(d.get("commission", 0.0) for d in deals),
            "total_swap": sum(d.get("swap", 0.0) for d in deals),
            "total_volume": sum(d.get("volume", 0.0) for d in deals),
            "net_pnl": sum(d.get("profit", 0.0) + d.get("commission", 0.0) + d.get("swap", 0.0) for d in deals),
        }
        
        if position:
            summary["current_profit"] = position.get("profit", 0.0)
            summary["current_swap"] = position.get("swap", 0.0)
            summary["price_open"] = position.get("price_open")
            summary["price_current"] = position.get("price_current")
            summary["sl"] = position.get("sl")
            summary["tp"] = position.get("tp")
        
        if deals:
            entry_deals = [d for d in deals if d.get("entry") == "IN"]
            exit_deals = [d for d in deals if d.get("entry") == "OUT"]
            if entry_deals:
                summary["entry_price"] = entry_deals[0].get("price")
                summary["entry_time"] = entry_deals[0].get("time")
            if exit_deals:
                summary["exit_price"] = exit_deals[-1].get("price")
                summary["exit_time"] = exit_deals[-1].get("time")
        
        return jsonify({
            "status": status,
            "pending_order": pending_order,
            "position": position,
            "order_history": order_history,
            "deals": deals,
            "summary": summary,
        })
    except (ValidationError, ValueError) as e:
        return format_error_response(e, 400)
    except MT5ReadError as e:
        logger.error("get_trade_lifecycle: %s", e)
        return jsonify({"error": "MT5 read failed", "detail": str(e), "status": "UNKNOWN"}), 503
    except Exception as e:
        logger.error("get_trade_lifecycle error: %s", e)
        return format_error_response(e, 500, endpoint="/trade_lifecycle", request_context=get_request_context(request))


@trade_lifecycle_bp.route("/trade_status", methods=["GET"])
@require_api_key
@swag_from(trade_status_spec)
def get_trade_status():
    try:
        ticket = request.args.get("ticket", type=int)
        if not ticket:
            raise ValidationError("ticket required", field="ticket", endpoint="/trade_status", request_context=get_request_context(request))
        
        pending_order = _check_pending_order(ticket)
        if pending_order:
            return jsonify({
                "ticket": ticket,
                "status": "PENDING",
                "is_open": True,
                "symbol": pending_order.get("symbol"),
                "type": pending_order.get("type"),
                "price_open": pending_order.get("price_open"),
                "sl": pending_order.get("sl"),
                "tp": pending_order.get("tp"),
            })
        
        position = _fetch_position_by_ticket(ticket)
        if position:
            return jsonify({
                "ticket": ticket,
                "status": "RUNNING",
                "is_open": True,
                "current_profit": position.get("profit"),
                "current_swap": position.get("swap"),
                "symbol": position.get("symbol"),
                "type": position.get("type"),
                "price_open": position.get("price_open"),
                "price_current": position.get("price_current"),
                "sl": position.get("sl"),
                "tp": position.get("tp"),
                "volume": position.get("volume"),
            })
        
        to_date = datetime.now(MT5_TIMEZONE) + timedelta(hours=BROKER_TIMEZONE_OFFSET)
        from_date = to_date - timedelta(days=30)
        deals = _fetch_deals_by_ticket(ticket, from_date, to_date)
        order_history = _fetch_order_by_ticket(ticket)
        status = _determine_trade_status(None, None, deals, order_history)
        
        result = {"ticket": ticket, "status": status, "is_open": False}
        if deals:
            total_profit = sum(d.get("profit", 0.0) for d in deals)
            total_commission = sum(d.get("commission", 0.0) for d in deals)
            total_swap = sum(d.get("swap", 0.0) for d in deals)
            net_pnl = total_profit + total_commission + total_swap
            result.update({
                "total_profit": total_profit,
                "total_commission": total_commission,
                "total_swap": total_swap,
                "net_pnl": net_pnl,
                "symbol": deals[0].get("symbol"),
                "type": deals[0].get("type"),
            })
        if order_history:
            result.update({
                "symbol": order_history.get("symbol"),
                "type": order_history.get("type"),
            })
        return jsonify(result)
    except (ValidationError, ValueError) as e:
        return format_error_response(e, 400)
    except MT5ReadError as e:
        logger.error("get_trade_status: %s", e)
        return jsonify({"error": "MT5 read failed", "detail": str(e), "status": "UNKNOWN"}), 503
    except Exception as e:
        logger.error("get_trade_status error: %s", e)
        return format_error_response(e, 500, endpoint="/trade_status", request_context=get_request_context(request))


@trade_lifecycle_bp.route("/trade_batch_status", methods=["POST"])
@require_api_key
@swag_from(batch_trade_status_spec)
def get_batch_trade_status():
    try:
        data = request.get_json()
        if not data or "tickets" not in data:
            raise ValidationError("tickets list required", field="tickets", endpoint="/trade_batch_status", request_context=get_request_context(request))
        
        tickets = data["tickets"]
        if not isinstance(tickets, list):
            raise ValidationError("tickets must be a list", field="tickets", endpoint="/trade_batch_status", request_context=get_request_context(request))
        
        results = []
        for ticket in tickets:
            try:
                pending_order = _check_pending_order(ticket)
                position = _fetch_position_by_ticket(ticket)
                if pending_order:
                    results.append({
                        "ticket": ticket,
                        "status": "PENDING",
                        "is_open": True,
                        "symbol": pending_order.get("symbol"),
                    })
                elif position:
                    results.append({
                        "ticket": ticket,
                        "status": "RUNNING",
                        "is_open": True,
                        "current_profit": position.get("profit"),
                        "symbol": position.get("symbol"),
                        "sl": position.get("sl"),
                        "tp": position.get("tp"),
                    })
                else:
                    to_date = datetime.now(MT5_TIMEZONE) + timedelta(hours=BROKER_TIMEZONE_OFFSET)
                    from_date = to_date - timedelta(days=7)
                    deals = _fetch_deals_by_ticket(ticket, from_date, to_date)
                    if deals:
                        net_pnl = sum(d.get("profit", 0.0) + d.get("commission", 0.0) + d.get("swap", 0.0) for d in deals)
                        status = "CLOSED_PROFIT" if net_pnl > 0.01 else "CLOSED_LOSS" if net_pnl < -0.01 else "CLOSED_BREAKEVEN"
                        results.append({
                            "ticket": ticket,
                            "status": status,
                            "is_open": False,
                            "total_profit": sum(d.get("profit", 0.0) for d in deals),
                            "total_commission": sum(d.get("commission", 0.0) for d in deals),
                            "total_swap": sum(d.get("swap", 0.0) for d in deals),
                            "net_pnl": net_pnl,
                            "symbol": deals[0].get("symbol") if deals else None,
                        })
                    else:
                        results.append({"ticket": ticket, "status": "UNKNOWN", "is_open": False})
            except Exception as e:
                logger.error("Batch status error for ticket %d: %s", ticket, e)
                results.append({"ticket": ticket, "status": "ERROR", "error": str(e)})
        
        return jsonify({"results": results})
    except (ValidationError, ValueError) as e:
        return format_error_response(e, 400)
    except Exception as e:
        logger.error("get_batch_trade_status error: %s", e)
        return format_error_response(e, 500, endpoint="/trade_batch_status", request_context=get_request_context(request))


@trade_lifecycle_bp.route("/trade_search", methods=["GET"])
@trade_lifecycle_bp.route("/api/mt5/history", methods=["GET"])
@require_api_key
@swag_from(trade_search_spec)
def search_trades():
    try:
        symbol = request.args.get("symbol")
        magic = request.args.get("magic", type=int)
        status_filter = request.args.get("status")
        from_s = request.args.get("from_date")
        to_s = request.args.get("to_date")
        
        if not from_s or not to_s:
            to_date = datetime.now(MT5_TIMEZONE) + timedelta(hours=BROKER_TIMEZONE_OFFSET)
            from_date = to_date - timedelta(days=7)
        else:
            from_date = parse_iso_datetime(from_s)
            to_date = parse_iso_datetime(to_s)
        
        # Add wildcard to symbol if provided to catch suffixes like .pro, .m, etc.
        group_filter = symbol
        if group_filter and "*" not in group_filter:
            group_filter = f"{group_filter}*"
        
        deals = mt5.history_deals_get(int(from_date.timestamp()), int(to_date.timestamp()), group=group_filter or "*")
        if not deals:
            return jsonify({"trades": []}), 200
        
        position_map = {}
        for deal in deals:
            # Only BUY/SELL deals belong to trades. Balance/credit/charge/commission-correction deals
            # carry position_id 0 and would show up as a bogus "trade" with the deposit as profit.
            if deal.type not in (0, 1) or not deal.position_id:
                continue
            position_map.setdefault(deal.position_id, []).append(deal)
        
        trades = []
        for pos_id, pos_deals in position_map.items():
            if magic is not None and pos_deals[0].magic != magic:
                continue
            
            total_profit = sum(d.profit for d in pos_deals)
            total_commission = sum(d.commission for d in pos_deals)
            total_swap = sum(d.swap for d in pos_deals)
            net_pnl = total_profit + total_commission + total_swap
            status = "CLOSED_PROFIT" if net_pnl > 0.01 else "CLOSED_LOSS" if net_pnl < -0.01 else "CLOSED_BREAKEVEN"
            
            if status_filter and status != status_filter:
                continue
            
            entry_deals = [d for d in pos_deals if d.entry == 0]
            exit_deals = [d for d in pos_deals if d.entry == 1]
            
            trades.append({
                "position_id": pos_id,
                "ticket": pos_deals[0].order,
                "symbol": pos_deals[0].symbol,
                "type": pos_deals[0].type,
                "type_label": _get_order_type_label(pos_deals[0].type),
                "magic": pos_deals[0].magic,
                "status": status,
                "entry_time": _serialize_timestamp(entry_deals[0].time) if entry_deals else None,
                "exit_time": _serialize_timestamp(exit_deals[-1].time) if exit_deals else None,
                "time_open": _serialize_timestamp(entry_deals[0].time) if entry_deals else None,
                "time_close": _serialize_timestamp(exit_deals[-1].time) if exit_deals else None,
                "entry_price": float(entry_deals[0].price) if entry_deals else None,
                "exit_price": float(exit_deals[-1].price) if exit_deals else None,
                "price_open": float(entry_deals[0].price) if entry_deals else None,
                "price_close": float(exit_deals[-1].price) if exit_deals else None,
                "volume": float(entry_deals[0].volume) if entry_deals else float(pos_deals[0].volume),
                "profit": total_profit,
                "commission": total_commission,
                "swap": total_swap,
                "net_pnl": net_pnl,
                "deal_count": len(pos_deals),
            })
        
        return jsonify({"trades": trades, "count": len(trades)})
    except (ValidationError, ValueError) as e:
        return format_error_response(e, 400)
    except Exception as e:
        logger.error("search_trades error: %s", e)
        return format_error_response(e, 500, endpoint="/trade_search", request_context=get_request_context(request))

