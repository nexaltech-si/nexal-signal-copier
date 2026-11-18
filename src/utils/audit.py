"""
Audit trail: durable, non-blocking records of operationally important events
(provider switches, settings changes, stream loss, ERROR-level logs) in the
`system_events` table. Never raises and never blocks the caller.
"""
import asyncio
import time
from typing import Any, Dict, Optional

from loguru import logger

from src.utils.tasks import spawn

_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "HASH", "SESSION", "PHONE")


def redact(key: str, value: Any) -> Any:
    """Mask secret values so they never reach the audit table or the logs."""
    if any(m in key.upper() for m in _SECRET_MARKERS):
        return "***" if value not in (None, "") else value
    text = repr(value)
    return value if len(text) <= 200 else text[:197] + "..."


def audit(event_type: str, message: str, severity: str = "LOW", details: Optional[Dict[str, Any]] = None,
          module: Optional[str] = None) -> None:
    """Record an event. event_type: ERROR | WARNING | INFO | TRADE | NOTIFICATION | AUDIT."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # no loop (script/test) - nothing to schedule on

    async def _write():
        try:
            from src.core.database_service import db_service
            await db_service.log_system_event(event_type, severity, message, details=details, module=module)
        except Exception as e:  # pragma: no cover - audit must never break the caller
            logger.debug(f"Audit write failed: {e!r}")

    spawn(_write(), name="audit")


class ErrorAuditSink:
    """
    loguru sink: persists ERROR+ log records to system_events, de-duplicated (same message
    at most once per `dedupe_seconds`) and bounded, so an error storm cannot flood the DB.
    """

    def __init__(self, dedupe_seconds: float = 60.0, max_tracked: int = 500):
        self._seen: Dict[str, float] = {}
        self._dedupe = dedupe_seconds
        self._max = max_tracked

    def __call__(self, message) -> None:
        rec = message.record
        text = rec["message"]
        if text.startswith(("❌ Failed to log system event", "Audit write failed")):
            return
        now = time.monotonic()
        key = f"{rec['name']}:{rec['function']}:{text[:120]}"
        last = self._seen.get(key)
        if last is not None and now - last < self._dedupe:
            return
        if len(self._seen) >= self._max:
            self._seen.clear()
        self._seen[key] = now
        exc = rec["exception"]
        audit(
            "ERROR",
            text[:500],
            severity="CRITICAL" if rec["level"].no >= 50 else "HIGH",
            details={"exception": repr(exc.value)} if exc and exc.value else None,
            module=f"{rec['name']}:{rec['function']}:{rec['line']}",
        )


def install_error_audit_sink() -> int:
    """Attach the ERROR audit sink to loguru; returns the handler id."""
    return logger.add(ErrorAuditSink(), level="ERROR", format="{message}", enqueue=False, catch=True)
