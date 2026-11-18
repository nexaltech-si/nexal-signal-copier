"""
Telegram login / sign-out for the dashboard's Connections page.

Replaces the old token-in-URL Flask login page (port 5001). Reached only through
the dashboard's owner-only /api/telegram/auth route, and like the rest of this
API it requires X-Internal-Token. Bodies are read by hand rather than through
pydantic models so a validation error can never echo a code or 2FA password
back in the response, and nothing here logs them.
"""
from fastapi import APIRouter, HTTPException, Request

from src.integrations.telegram.listener import TelegramAuthError

telegram_auth_router = APIRouter(prefix="/api/telegram/auth", tags=["telegram-auth"])


def _listener():
    from src.api.api_server import _telethon_listener
    if _telethon_listener is None:
        raise HTTPException(status_code=503, detail="Telegram listener not started")
    return _telethon_listener


async def _field(request: Request, name: str) -> str:
    try:
        body = await request.json()
    except Exception:
        body = {}
    value = body.get(name) if isinstance(body, dict) else None
    return value if isinstance(value, str) else ""


async def _run(step):
    try:
        return await step
    except TelegramAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


@telegram_auth_router.get("/status")
async def auth_status():
    return _listener().auth_status()


@telegram_auth_router.post("/send-code")
async def send_code(request: Request):
    return await _run(_listener().begin_login(await _field(request, "phone")))


@telegram_auth_router.post("/code")
async def submit_code(request: Request):
    return await _run(_listener().submit_code(await _field(request, "code")))


@telegram_auth_router.post("/password")
async def submit_password(request: Request):
    return await _run(_listener().submit_password(await _field(request, "password")))


@telegram_auth_router.post("/cancel")
async def cancel_login():
    return await _run(_listener().cancel_login())


@telegram_auth_router.post("/sign-out")
async def sign_out():
    return await _run(_listener().sign_out())
