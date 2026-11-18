"""
One-click conversion of a pending order (limit or stop) into a market order at
the same money risk.

A pending order fills at its own price; at market the entry is the current ask
(BUY) or bid (SELL), so the distance to the stop loss changes. The lot size is
scaled by old SL distance / new SL distance and rounded DOWN to the volume step,
so the money at risk to the SL never exceeds the original (tick value is the
same symbol's on both sides, so it cancels out). Only when even the minimum lot
is bigger than that is the risk higher, and the plan says by how much.

The order is cancelled first, then the market order is sent: never two live
entries for one order. If the market order fails, the pending order is put back.
The trade record keeps its signal, magic number and settings; only the ticket,
status, lots and entry change. The whole swap runs under the order-sync lock so
a sync pass can't see the order gone before the position is linked.
"""
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger

CONVERTIBLE = {
    "ORDER_TYPE_BUY_LIMIT": "BUY_LIMIT",
    "ORDER_TYPE_SELL_LIMIT": "SELL_LIMIT",
    "ORDER_TYPE_BUY_STOP": "BUY_STOP",
    "ORDER_TYPE_SELL_STOP": "SELL_STOP",
}


@dataclass
class ConversionPlan:
    order_id: str
    symbol: str = ""
    side: str = ""                        # BUY | SELL
    pending_type: str = ""                # BUY_LIMIT, SELL_STOP, ...
    pending_price: float = 0.0
    market_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    old_volume: float = 0.0
    new_volume: Optional[float] = None
    risk_change_pct: Optional[float] = None  # new risk vs original, e.g. -1.8 (rounded down)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None


def plan_conversion(order: dict, bid: float, ask: float, spec: dict) -> ConversionPlan:
    """Lots and checks for turning `order` (normalized pending order) into a market order now."""
    plan = ConversionPlan(order_id=str(order.get("id", "")), symbol=order.get("symbol", ""))
    pending_type = CONVERTIBLE.get(order.get("type", ""))
    if not pending_type:
        plan.error = f"{order.get('type', 'This order type')} can't be converted (limit and stop orders only)"
        return plan
    is_buy = pending_type.startswith("BUY")
    plan.side = "BUY" if is_buy else "SELL"
    plan.pending_type = pending_type
    plan.pending_price = float(order.get("openPrice") or 0)
    plan.stop_loss = order.get("stopLoss") or None
    plan.take_profit = order.get("takeProfit") or None
    plan.old_volume = float(order.get("volume") or 0)

    market = ask if is_buy else bid
    if not market or market <= 0:
        plan.error = f"No live price for {plan.symbol} — market closed?"
        return plan
    plan.market_price = market
    sl, tp = plan.stop_loss, plan.take_profit
    if sl and (market <= sl if is_buy else market >= sl):
        plan.error = f"Price {market} is already past the stop loss {sl}"
        return plan
    if tp and (market >= tp if is_buy else market <= tp):
        plan.error = f"Price {market} is already past the take profit {tp}"
        return plan

    step = float(spec.get("volumeStep") or 0.01)
    vmin = float(spec.get("volumeMin") or step)
    vmax = float(spec.get("volumeMax") or 100.0)
    old_dist = abs(plan.pending_price - sl) if sl else 0.0
    if not sl or old_dist <= 0:
        plan.new_volume = plan.old_volume
        plan.warnings.append(
            "No stop loss on this order — risk is not defined, so the lot size is kept"
            if not sl else "Stop loss sits at the entry price — the lot size is kept")
        return plan

    new_dist = abs(market - sl)
    raw = plan.old_volume * old_dist / new_dist
    # Down to the step (tiny epsilon: 0.03/0.01 is 2.9999999999999996 in floats).
    new = round(math.floor(raw / step + 1e-9) * step, 8)
    if new < vmin:
        new = vmin
        plan.warnings.append(f"The minimum lot {vmin} is more than the same risk allows")
    new = min(new, vmax)
    plan.new_volume = new
    plan.risk_change_pct = round((new * new_dist / (plan.old_volume * old_dist) - 1) * 100, 1)
    if plan.risk_change_pct > 0:
        plan.warnings.append(f"Risk is {plan.risk_change_pct}% higher than the original order")
    return plan


async def _find_order(provider, order_id: str) -> Optional[dict]:
    orders = await provider.get_all_pending_orders(use_cache=False) or []
    return next((o for o in orders if str(o.get("id")) == str(order_id)), None)


async def preview_conversion(order_id: str) -> ConversionPlan:
    from src.integrations.trading.provider_factory import create_trading_provider
    provider = create_trading_provider()
    order = await _find_order(provider, order_id)
    if not order:
        return ConversionPlan(order_id=str(order_id), error="Order not found — already filled or cancelled?")
    price = await provider.get_symbol_price(order["symbol"])
    spec = await provider.get_symbol_specification(order["symbol"])
    return plan_conversion(order, price.get("bid"), price.get("ask"), spec)


async def convert_to_market(order_id: str) -> dict:
    """Cancel the pending order and open it at market with the same risk. Re-plans on live data."""
    from src.integrations.trading.provider_factory import create_trading_provider
    from src.integrations.trading.mt5rest_provider import order_tickets
    from src.services.order_sync_service import order_sync_service

    provider = create_trading_provider()
    if not hasattr(provider, "place_market_order"):
        return {"success": False, "error": "Only available with the MT5 REST provider"}

    async with order_sync_service.lock:
        order = await _find_order(provider, order_id)
        if not order:
            return {"success": False, "error": "Order not found — already filled or cancelled?"}
        price = await provider.get_symbol_price(order["symbol"])
        spec = await provider.get_symbol_specification(order["symbol"])
        plan = plan_conversion(order, price.get("bid"), price.get("ask"), spec)
        if plan.error:
            return {"success": False, "error": plan.error, "plan": asdict(plan)}

        magic = int(order.get("magic") or 0)
        comment = order.get("comment") or ""
        try:
            await provider.cancel_order(plan.order_id)
        except Exception as e:
            return {"success": False, "error": f"Could not cancel the pending order: {e}", "plan": asdict(plan)}

        try:
            result = await provider.place_market_order(
                plan.symbol, plan.side == "BUY", plan.new_volume,
                plan.stop_loss, plan.take_profit, magic, comment)
        except Exception as e:
            logger.error(f"❌ Market order for converted {plan.order_id} failed: {e} — restoring the pending order")
            restored = await _restore_pending(provider, plan, magic, comment)
            return {"success": False, "plan": asdict(plan),
                    "error": f"Market order failed: {e}. "
                             + (f"The pending order was put back as #{restored}." if restored
                                else "The pending order could NOT be put back — check MT5.")}

        _, position_id, deal_id = order_tickets(result)
        fill_price = float(result.get("price") or plan.market_price)
        await _relink_trade(plan, position_id, deal_id, fill_price)

    logger.success(f"✅ Pending {plan.pending_type} #{plan.order_id} → market {plan.side} #{position_id} "
                   f"{plan.old_volume} → {plan.new_volume} lots @ {fill_price}")
    return {"success": True, "position_id": position_id, "fill_price": fill_price, "plan": asdict(plan)}


async def _restore_pending(provider, plan: ConversionPlan, magic: int, comment: str) -> Optional[str]:
    try:
        result = await provider.place_pending_order(
            plan.symbol, plan.pending_type, plan.old_volume, plan.pending_price,
            plan.stop_loss, plan.take_profit, magic, comment)
        new_id = str(result.get("order") or "")
        if new_id and new_id != "0":
            await _relink_pending(plan.order_id, new_id)
        return new_id or None
    except Exception as e:
        logger.error(f"❌ Could not restore pending order {plan.order_id}: {e}")
        return None


async def _trades_for_order(order_id: str):
    from src.core.database_service import db_service
    return await db_service.db.trade.find_many(
        where={"orderId": str(order_id), "status": {"notIn": ["CLOSED", "CANCELLED", "FAILED"]}})


async def _relink_trade(plan: ConversionPlan, position_id: str, deal_id: Optional[str], fill_price: float):
    """Point the order's trade record at the new position; keep signal, magic and settings."""
    from src.core.database_service import db_service
    trades = await _trades_for_order(plan.order_id)
    if not trades:
        logger.warning(f"⚠️ No trade record for converted order {plan.order_id} — order sync will adopt the position")
        return
    for trade in trades:
        await db_service.db.trade.update(where={"id": trade.id}, data={
            "orderId": position_id,
            "positionId": position_id,
            "dealId": deal_id,
            "status": "RUNNING",
            "lotSize": plan.new_volume,
            "entryPrice": fill_price,
            "executedAt": datetime.now(timezone.utc),
        })
        await db_service.log_trade_action(
            trade_id=trade.id, action_type="CONVERT_TO_MARKET", success=True,
            triggered_by="dashboard", trigger_source="convert_to_market",
            details=(f"Pending {plan.pending_type} #{plan.order_id} @ {plan.pending_price} → market "
                     f"{plan.side} #{position_id} @ {fill_price}; lots {plan.old_volume} → {plan.new_volume} "
                     f"(risk {plan.risk_change_pct:+}% vs original)" if plan.risk_change_pct is not None
                     else f"Pending {plan.pending_type} #{plan.order_id} → market #{position_id} @ {fill_price}"),
        )
        if trade.signalId:
            await db_service.update_signal_status_from_trades(trade.signalId)


async def _relink_pending(old_id: str, new_id: str):
    from src.core.database_service import db_service
    for trade in await _trades_for_order(old_id):
        await db_service.db.trade.update(where={"id": trade.id}, data={"orderId": new_id})
