"""
SimulatorService — singleton that manages simulation state for the dashboard.

Responsibilities:
- Holds a reference to the shared Telegram client (set by main.py)
- Runs simulations as background asyncio tasks
- Broadcasts real-time events to SSE subscribers
- Persists results and exposes them via get_result / list_results
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from loguru import logger


class SimStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    CANCELLED = "cancelled"
    COMPLETE = "complete"
    ERROR = "error"


class SimulatorService:
    """Singleton service used by the FastAPI router and main.py."""

    def __init__(self) -> None:
        self._telegram_client = None
        self._status: SimStatus = SimStatus.IDLE
        self._current_task: Optional[asyncio.Task] = None
        self._engine = None                     # TradingSimulator instance
        self._last_results = None               # SimulationResults from last run
        self._progress: Dict[str, Any] = {}    # live progress snapshot
        self._error: Optional[str] = None

        # SSE pub/sub queues
        self._subscribers: Set[asyncio.Queue] = set()

        self.results_dir = Path("simulator/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)

    # ── Telegram client sharing ───────────────────────────────────────────────

    def set_telegram_client(self, client) -> None:
        """Called by main.py after TelethonListener authenticates."""
        self._telegram_client = client
        logger.info("SimulatorService: shared Telegram client registered")

    @property
    def has_client(self) -> bool:
        return self._telegram_client is not None

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def status(self) -> SimStatus:
        return self._status

    def get_status_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "status": self._status.value,
            "has_client": self.has_client,
            "progress": self._progress,
            "error": self._error,
        }
        if self._last_results is not None:
            out["last_results"] = self._last_results.summary()
        return out

    # ── Run / stop ────────────────────────────────────────────────────────────

    async def start_simulation(
        self,
        channel_id: int,
        channel_name: str,
        start_date: datetime,
        end_date: datetime,
        limit: int = 1000,
        enable_brain: bool = False,
        source: str = "telegram",
    ) -> None:
        if self._status == SimStatus.RUNNING:
            raise RuntimeError("A simulation is already running.")

        self._status = SimStatus.RUNNING
        self._error = None
        self._progress = {
            "channel_name": channel_name,
            "current": 0,
            "total": 0,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self._last_results = None

        self._current_task = asyncio.create_task(
            self._run(
                channel_id=channel_id,
                channel_name=channel_name,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                enable_brain=enable_brain,
                source=source,
            )
        )
        self._current_task.add_done_callback(self._on_task_done)

    def stop_simulation(self) -> None:
        if self._engine:
            self._engine.cancel()
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        self._status = SimStatus.CANCELLED

    # ── Internal run ─────────────────────────────────────────────────────────

    async def _run(
        self,
        channel_id: int,
        channel_name: str,
        start_date: datetime,
        end_date: datetime,
        limit: int,
        enable_brain: bool,
        source: str = "telegram",
    ) -> None:
        from simulator.engine import TradingSimulator

        # AI config is ALWAYS the live bot's database-backed config — never .env.
        # signal_service.ai_config reflects whatever the user configured via the
        # dashboard settings UI (provider, vision_provider, models, fallbacks),
        # because settings.reload_from_db() + signal_service.reinitialize() keep
        # it in sync with the database. There is no fallback here on purpose: a
        # silent fallback to a separately-derived .env config is exactly what
        # caused vision_provider to resolve to "deepseek" (no vision support)
        # instead of the database-configured "gemini", breaking image extraction
        # with a 400 "unknown variant image_url" error. If this import fails,
        # the simulator must not run rather than run with the wrong AI config.
        from src.services.signal_service import signal_service
        sim_config = signal_service.ai_config

        if source == "discord":
            from src.integrations.discord.listener import discord_listener
            self._engine = TradingSimulator(
                message_fetcher=discord_listener.replay_messages,
                enable_brain=enable_brain,
            )
        elif self.has_client:
            self._engine = TradingSimulator(
                telegram_client=self._telegram_client,
                enable_brain=enable_brain,
            )
        else:
            api_id = os.getenv("TELEGRAM_API_ID")
            api_hash = os.getenv("TELEGRAM_API_HASH")
            phone = os.getenv("TELEGRAM_PHONE")
            if not all([api_id, api_hash, phone]):
                raise RuntimeError(
                    "No shared Telegram client and no credentials in .env "
                    "(TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE)."
                )
            self._engine = TradingSimulator(
                api_id=int(api_id),
                api_hash=api_hash,
                phone=phone,
                enable_brain=enable_brain,
            )

        try:
            await self._engine.initialize(sim_config)

            await self._broadcast(
                {"type": "simulation_started", "channel_name": channel_name, "limit": limit}
            )

            results = await self._engine.run(
                channel_id=channel_id,
                channel_name=channel_name,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                on_progress=self._on_progress,
            )

            self._last_results = results
            self._status = SimStatus.COMPLETE
            await self._broadcast(
                {"type": "simulation_complete", "summary": results.summary()}
            )

        except asyncio.CancelledError:
            self._status = SimStatus.CANCELLED
            await self._broadcast({"type": "simulation_cancelled"})
        except Exception as exc:
            self._status = SimStatus.ERROR
            self._error = str(exc)
            logger.error(f"Simulation error: {exc}")
            await self._broadcast({"type": "simulation_error", "error": str(exc)})
            raise
        finally:
            await self._engine.close()
            self._engine = None

    async def _on_progress(self, current: int, total: int, trade) -> None:
        self._progress.update({"current": current, "total": total})

        event: Dict[str, Any] = {
            "type": "message_processed",
            "current": current,
            "total": total,
            "trade": {
                "message_id": trade.message_id,
                "timestamp": trade.timestamp.isoformat(),
                "intent": trade.intent,
                "intent_source": trade.intent_source,
                "extraction_method": trade.extraction_method,
                "symbol": trade.ai_symbol or trade.pattern_symbol,
                "action": trade.ai_action or trade.pattern_action,
                "ai_order_type": trade.ai_order_type or trade.pattern_order_type,
                "command_action": trade.command_action,
                "has_image": trade.has_image,
                "is_reply": trade.is_reply,
                "reply_to_message_id": trade.reply_to_message_id,
                "brain_verdict": trade.brain_verdict,
                "extraction_error": trade.extraction_error,
                "original_message": trade.original_message[:500],
                "ai_entry": trade.ai_entry if trade.ai_entry is not None else trade.pattern_entry,
                "ai_sl": trade.ai_sl if trade.ai_sl is not None else trade.pattern_sl,
                "ai_tp": trade.ai_tp or trade.pattern_tp,
                "command_value": trade.command_value,
                "command_percentage": trade.command_percentage,
                # Reply replay through the live ReplyHandlerService
                "reply_state": trade.reply_state,
                "reply_ai_action": trade.reply_ai_action,
                "reply_broker_calls": trade.reply_broker_calls,
                "reply_result": trade.reply_result,
                "reply_state_after": trade.reply_state_after,
            },
        }
        await self._broadcast(event)

    def _on_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            self._status = SimStatus.CANCELLED
        elif task.exception():
            self._status = SimStatus.ERROR

    # ── Results access ────────────────────────────────────────────────────────

    def list_results(self) -> List[Dict[str, Any]]:
        files = sorted(self.results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        out = []
        for f in files[:50]:                # cap at 50 most recent
            stat = f.stat()
            out.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return out

    def get_result(self, filename: str) -> Optional[Dict]:
        # Prevent path traversal
        path = (self.results_dir / filename).resolve()
        if not str(path).startswith(str(self.results_dir.resolve())):
            raise ValueError("Invalid filename")
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def delete_result(self, filename: str) -> bool:
        path = (self.results_dir / filename).resolve()
        if not str(path).startswith(str(self.results_dir.resolve())):
            raise ValueError("Invalid filename")
        if path.exists():
            path.unlink()
            return True
        return False

    # ── SSE pub/sub ──────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def _broadcast(self, event: Dict[str, Any]) -> None:
        dead: Set[asyncio.Queue] = set()
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.add(q)
        for q in dead:
            self._subscribers.discard(q)


# Singleton instance imported everywhere
simulator_service = SimulatorService()
