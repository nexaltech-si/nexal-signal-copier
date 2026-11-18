"""
Shared-secret authentication for the internal API server (audit finding H-05).

The API on :8001 serves decrypted settings, trade execution and Telegram
access. It was protected only by Docker networking, but it is attached to
mt5-net, which it shares with the mt5 container (a full KasmVNC desktop). Every
request now has to carry X-Internal-Token; the dashboard adds it centrally (see
dashboard/src/instrumentation.ts).

Token source, in order:
  1. INTERNAL_API_TOKEN, if set.
  2. Otherwise HMAC-SHA256(SETTINGS_ENCRYPTION_KEY, "nexal-internal-api-v1"). Both
     containers already load the same .env, so this needs no extra config;
     the dashboard derives the same value.
With neither available, every protected request is refused (fail closed).
"""
import hashlib
import hmac
import os
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger

HEADER = "X-Internal-Token"
DERIVATION_LABEL = b"nexal-internal-api-v1"
# Liveness probes only. Everything else needs the token.
PUBLIC_PATHS = frozenset({"/health"})


def resolve_internal_token(env=os.environ) -> Optional[str]:
    explicit = (env.get("INTERNAL_API_TOKEN") or "").strip()
    if explicit:
        return explicit
    base = (env.get("SETTINGS_ENCRYPTION_KEY") or "").strip()
    if base:
        return hmac.new(base.encode(), DERIVATION_LABEL, hashlib.sha256).hexdigest()
    return None


def is_authorized(path: str, presented: Optional[str], expected: Optional[str]) -> bool:
    if path in PUBLIC_PATHS:
        return True
    if not expected or not presented:
        return False
    return hmac.compare_digest(presented.encode(), expected.encode())


def install_internal_auth(app, env=os.environ) -> None:
    expected = resolve_internal_token(env)
    if not expected:
        logger.critical(
            "Internal API token unavailable (set INTERNAL_API_TOKEN or SETTINGS_ENCRYPTION_KEY) "
            "— all API requests except /health will be refused."
        )

    @app.middleware("http")
    async def _internal_token_guard(request: Request, call_next):
        if request.method == "OPTIONS" or is_authorized(request.url.path, request.headers.get(HEADER), expected):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        logger.warning(f"🚫 Internal API: rejected {request.method} {request.url.path} from {client}")
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
