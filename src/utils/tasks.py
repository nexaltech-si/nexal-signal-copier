"""Background task helper: keeps a strong reference and always logs failures."""
import asyncio
from typing import Any, Coroutine, Optional, Set

from loguru import logger

_tasks: Set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], name: Optional[str] = None) -> asyncio.Task:
    """
    Fire-and-forget replacement for asyncio.create_task / ensure_future.

    A bare create_task result can be garbage-collected mid-flight and its exception is
    only reported (if at all) at interpreter shutdown. spawn() keeps the task alive until
    it finishes and logs any exception with the task name.
    """
    task = asyncio.ensure_future(coro)
    if name and hasattr(task, "set_name"):
        task.set_name(name)
    _tasks.add(task)

    def _done(t: asyncio.Task):
        _tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.opt(exception=exc).error(f"Background task '{t.get_name() if hasattr(t, 'get_name') else t}' failed: {exc!r}")

    task.add_done_callback(_done)
    return task
