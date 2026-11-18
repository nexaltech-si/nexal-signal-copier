"""
Reporting trade-management results (close, modify SL/TP, break-even, partial close,
cancel) that succeeded only in part.

Action handlers return {"success": True, "errors": [...]} when at least one
position/order was changed and others failed. Treating that as plain success sent
"✅ Command Executed" while, say, one of three positions kept its old stop — so a
partial failure is logged at ERROR and announced with what was NOT changed.
"""
import html
from typing import List

from loguru import logger

MAX_LISTED = 5


def partial_failures(result: dict) -> List[str]:
    """The per-item errors of an action that succeeded only in part ([] otherwise)."""
    if not result or not result.get('success') or result.get('ignored'):
        return []
    errors = result.get('errors') or []
    if isinstance(errors, str):
        errors = [errors]
    return [str(e) for e in errors if e]


def failure_block(failures: List[str]) -> str:
    """HTML block listing what failed, for a Telegram notification."""
    lines = "\n".join(f"• {html.escape(f[:200])}" for f in failures[:MAX_LISTED])
    more = f"\n• … and {len(failures) - MAX_LISTED} more" if len(failures) > MAX_LISTED else ""
    return (f"\n\n❌ <b>Failed on {len(failures)} item(s) — these were NOT changed, check them:</b>\n"
            f"{lines}{more}")


def log_partial_failure(failures: List[str], context: str) -> None:
    logger.error(f"⚠️ {context} partly executed — {len(failures)} item(s) failed: {failures}")
