"""
Notification / Web Push endpoints used by the dashboard.

The dashboard reads and writes the inbox and push subscriptions directly through
its own Prisma client; these endpoints only expose what lives in the bot process:
the VAPID public key and the push sender.
"""
from fastapi import APIRouter

from src.services.event_pusher import event_pusher

notifications_router = APIRouter(prefix="/api/push", tags=["notifications"])


@notifications_router.get("/vapid-public-key")
async def vapid_public_key():
    return {"publicKey": event_pusher.vapid_public_key()}


@notifications_router.post("/test")
async def send_test_push():
    stats = await event_pusher.push(
        "Test notification",
        "Push notifications are working on this device.",
        type="SYSTEM",
        severity="SUCCESS",
        url="/",
    )
    return stats
