"""
Pending-order actions for the dashboard that need the bot (DB records, sync lock),
not just the MT5 bridge.
"""
from dataclasses import asdict

from fastapi import APIRouter
from loguru import logger

orders_router = APIRouter(prefix="/api/orders")


@orders_router.get("/{order_id}/to-market")
async def preview_to_market(order_id: str):
    """What converting this pending order to market would do now: price, lots, risk."""
    from src.services.order_conversion_service import preview_conversion
    try:
        return asdict(await preview_conversion(order_id))
    except Exception as e:
        logger.warning(f"⚠️ To-market preview for {order_id} failed: {e}")
        return {"order_id": order_id, "error": str(e)}


@orders_router.post("/{order_id}/to-market")
async def convert_to_market(order_id: str):
    """Cancel the pending order and open it at market with the same money risk."""
    from src.services.order_conversion_service import convert_to_market as convert
    try:
        return await convert(order_id)
    except Exception as e:
        logger.error(f"❌ To-market conversion of {order_id} failed: {e}")
        return {"success": False, "error": str(e)}
