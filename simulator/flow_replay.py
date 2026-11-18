"""
Flow replay — the bot-side half.

Fetches a channel's real messages with the live Telegram client, starts the
replay worker (simulator/flow_replay_worker.py) in its own process, answers the
worker's requests for instrument data and M1 history from the live broker
connection (read-only), and keeps the worker's events for the dashboard.

Isolation: the worker gets a copy of the bot's settings and an EMPTY database
with the same tables; its broker is simulated. Nothing it does can place,
change or close an order on the live account, write to the live database or
send a Telegram message.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "simulator" / "results"

# Never handed to the worker: live account access, Telegram, the live database.
_PRIVATE_PREFIXES = ("telegram_", "metaapi_", "mt5_rest_", "database_", "redis_", "ea_", "internal_", "vapid_",
                     "clerk_", "authorized_", "settings_encryption")
# Fallback instrument data when the live broker cannot be asked (bot in dry run, broker offline).
_DEFAULT_SPECS = {
    "XAUUSD": dict(contract=100.0, spread=0.30, digits=2, tick_value=1.0),
    "XAGUSD": dict(contract=5000.0, spread=0.03, digits=3, tick_value=5.0),
    "BTCUSD": dict(contract=1.0, spread=12.0, digits=2, tick_value=0.01),
    "ETHUSD": dict(contract=1.0, spread=2.0, digits=2, tick_value=0.01),
    "US30": dict(contract=1.0, spread=2.0, digits=1, tick_value=0.1),
    "NAS100": dict(contract=1.0, spread=1.5, digits=1, tick_value=0.1),
}
_FX_SPEC = dict(contract=100000.0, spread=0.00012, digits=5, tick_value=1.0)
_JPY_SPEC = dict(contract=100000.0, spread=0.012, digits=3, tick_value=0.65)


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def clone_schema(live_db: str, target: str, channel_id: Optional[str] = None) -> None:
    """An empty database with the live one's tables; the owner's rules for this channel are copied."""
    src = sqlite3.connect(f"file:{live_db}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        rows = src.execute("SELECT type, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
                           "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END").fetchall()
        for _, sql in rows:
            dst.execute(sql)
        if channel_id is not None:
            cols = [r[1] for r in src.execute('PRAGMA table_info("channel_behavior_rules")')]
            if cols:
                names = ", ".join(f'"{c}"' for c in cols)
                marks = ", ".join("?" for _ in cols)
                for row in src.execute(f'SELECT {names} FROM "channel_behavior_rules" WHERE "channelId" = ?',
                                       (str(channel_id),)):
                    dst.execute(f'INSERT INTO "channel_behavior_rules" ({names}) VALUES ({marks})', row)
        dst.commit()
    finally:
        src.close()
        dst.close()


def export_settings() -> Dict[str, Any]:
    """The bot's current settings as plain values (what the dashboard shows, plus the AI keys)."""
    from config import settings
    out: Dict[str, Any] = {}
    for name in type(settings).model_fields:
        if name.startswith(_PRIVATE_PREFIXES):
            continue
        value = getattr(settings, name, None)
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, (bool, int, float, str)):
            out[name] = value
    return out


class FlowReplayService:
    def __init__(self) -> None:
        self.status = "idle"            # idle | fetching | running | done | error | stopped
        self.error: Optional[str] = None
        self.params: Dict[str, Any] = {}
        self.events: List[dict] = []
        self._task: Optional[asyncio.Task] = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._bars: Dict[str, dict] = {}

    # ── state for the API ────────────────────────────────────────────────────
    def state(self, since: int = 0) -> Dict[str, Any]:
        return {"status": self.status, "error": self.error, "params": self.params,
                "total": len(self.events), "events": self.events[max(since, 0):]}

    # ── run / stop ───────────────────────────────────────────────────────────
    async def start(self, channel_id: int, channel_name: str, start: datetime, end: datetime, limit: int = 300,
                    overrides: Optional[Dict[str, Any]] = None, source: str = "telegram") -> None:
        if self.status in ("fetching", "running"):
            raise RuntimeError("A flow replay is already running.")
        self.status, self.error, self.events, self._bars = "fetching", None, [], {}
        self.params = {"channel_id": channel_id, "channel_name": channel_name, "start": _utc(start).isoformat(),
                       "end": _utc(end).isoformat(), "limit": limit, "overrides": overrides or {},
                       "source": source}
        self._task = asyncio.create_task(self._run(channel_id, channel_name, _utc(start), _utc(end), limit,
                                                   overrides or {}, source))

    def _kill_worker(self) -> None:
        """The worker and everything it started (its database engine)."""
        proc = self._proc
        if proc is None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def stop(self) -> None:
        self._kill_worker()
        if self._task and not self._task.done():
            self._task.cancel()
        if self.status in ("fetching", "running"):
            self.status = "stopped"

    # ── messages from Discord ────────────────────────────────────────────────
    async def fetch_discord_messages(self, channel_id: int, start: datetime, end: datetime, limit: int) -> List[dict]:
        from src.integrations.discord.listener import discord_listener
        out: List[dict] = []
        for msg in await discord_listener.replay_messages(channel_id, start, end, limit):
            if not msg.text.strip() and not msg.media:
                continue
            out.append({"id": int(msg.id), "date": _utc(msg.date).isoformat(), "text": msg.text,
                        "reply_to": getattr(msg.reply_to, "reply_to_msg_id", None),
                        "edited": bool(msg.edit_date), "media": bool(msg.media)})
        return out                                         # already oldest first

    # ── messages from Telegram ───────────────────────────────────────────────
    async def fetch_messages(self, channel_id: int, start: datetime, end: datetime, limit: int) -> List[dict]:
        from simulator.service import simulator_service
        client = getattr(simulator_service, "_telegram_client", None)
        if client is None:
            raise RuntimeError("Telegram is not connected — the replay reads the channel through the bot's session.")
        out: List[dict] = []
        async for msg in client.iter_messages(channel_id, offset_date=end, limit=None):
            date = _utc(msg.date)
            if date < start:
                break
            if date > end:
                continue
            text = getattr(msg, "message", None) or getattr(msg, "text", None) or ""
            media = bool(getattr(msg, "media", None))
            if not text.strip() and not media:
                continue                                   # service messages
            reply = getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None)
            out.append({"id": int(msg.id), "date": date.isoformat(), "text": text, "reply_to": reply,
                        "edited": bool(getattr(msg, "edit_date", None)), "media": media})
            if len(out) >= limit:
                break
        out.reverse()                                      # oldest first
        return out

    # ── instrument data for the worker (read-only use of the live connection) ─
    async def _symbol_answer(self, symbol: str, start: datetime, end: datetime) -> dict:
        if symbol in self._bars:
            return self._bars[symbol]
        answer: dict = {"symbol": symbol, "spec": None, "bars": []}
        try:
            from config import settings
            from src.services.trading_service import trading_service
            from simulator import broker_clock
            provider = trading_service.trading_provider
            if settings.dry_run or settings.skip_metaapi or not getattr(provider, "is_connected", False):
                raise RuntimeError("broker not connected")
            spec = await provider.get_symbol_specification(symbol)
            quote = await provider.get_symbol_price(symbol)
            answer["spec"] = {"contract": float(spec.get("contractSize") or 100000),
                              "digits": int(spec.get("digits") or 5),
                              "spread": max(float(quote.get("ask", 0)) - float(quote.get("bid", 0)), 0.0),
                              "tick_value": 1.0}
            minutes = int((datetime.now(timezone.utc) - start).total_seconds() // 60) + 180
            candles = await provider.get_historical_candles(symbol, "1m", limit=max(500, min(minutes, 10_000)))
            times, rows = [], []
            for c in candles or []:
                t = c.get("time")
                if isinstance(t, (int, float)):
                    t = datetime.fromtimestamp(t / 1000 if t > 1e11 else t, tz=timezone.utc)
                elif not isinstance(t, datetime):
                    t = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
                times.append(_utc(t))
                rows.append((float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])))
            order = sorted(range(len(times)), key=times.__getitem__)
            times, rows = [times[i] for i in order], [rows[i] for i in order]
            # Bars are stamped in broker server time; the messages are real UTC. Measure the
            # broker's clock and put every bar on the real instant it stands for.
            offset, source = await broker_clock.measure(provider, symbol, times[-1] if times else None)
            times = [broker_clock.label_to_utc(t, offset) for t in times]
            answer["clock"] = {"offset_hours": offset, "source": source,
                               "follows_new_york_close": broker_clock.follows_new_york_close(offset)}
            self.events.append({"type": "clock", "symbol": symbol, **answer["clock"]})
            answer["bars"] = [[t.isoformat(), *r] for t, r in zip(times, rows) if start - _MARGIN <= t <= end + _MARGIN]
        except Exception as e:
            logger.warning(f"Flow replay: no live data for {symbol} ({e}) — using defaults, no price history")
            if answer["spec"] is None:
                base = symbol.upper()[:6]
                answer["spec"] = _DEFAULT_SPECS.get(base) or (
                    _JPY_SPEC if base.endswith("JPY") else _FX_SPEC if len(base) == 6 and base.isalpha() else None)
        self._bars[symbol] = answer
        return answer

    # ── the run ──────────────────────────────────────────────────────────────
    async def _run(self, channel_id: int, channel_name: str, start: datetime, end: datetime, limit: int,
                   overrides: Dict[str, Any], source: str = "telegram") -> None:
        workdir = Path(tempfile.mkdtemp(prefix="flow_replay_"))
        try:
            fetch = self.fetch_discord_messages if source == "discord" else self.fetch_messages
            messages = await fetch(channel_id, start, end, limit)
            if not messages:
                raise RuntimeError("No messages in this channel for the chosen period.")
            self.events.append({"type": "fetched", "messages": len(messages)})

            live_db = (os.environ.get("DATABASE_URL") or "").replace("file:", "", 1)
            if not live_db or not Path(live_db).exists():
                raise RuntimeError("The replay needs the bot's SQLite database to copy its tables from.")
            replay_db = workdir / "replay.db"
            await asyncio.to_thread(clone_schema, live_db, str(replay_db), str(channel_id))

            (workdir / "messages.json").write_text(json.dumps(messages, ensure_ascii=False))
            settings_file = workdir / "settings.json"
            settings_file.write_text(json.dumps({"channel_id": channel_id, "channel_name": channel_name,
                                                 "settings": export_settings(), "overrides": overrides}))
            os.chmod(settings_file, 0o600)                 # it carries the AI keys

            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {**os.environ, "DATABASE_URL": f"file:{replay_db}", "SIM_BRIDGE_PORT": str(port)}
            self._proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "simulator.flow_replay_worker",
                "--messages", str(workdir / "messages.json"), "--settings", str(settings_file),
                "--until", end.isoformat(), "--log", str(workdir / "worker.log"),
                cwd=str(ROOT), env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=16 * 1024 * 1024,
                start_new_session=True)                # its own process group: stopped as a whole
            self.status = "running"

            assert self._proc.stdout and self._proc.stdin
            finished = False
            async for raw in self._proc.stdout:
                line = raw.decode("utf-8", "replace")
                if not line.startswith("@@FLOW "):
                    continue
                event = json.loads(line[7:])
                if event["type"] == "need_symbol":
                    answer = await self._symbol_answer(event["symbol"], start, end)
                    self._proc.stdin.write((json.dumps(answer) + "\n").encode())
                    await self._proc.stdin.drain()
                    continue
                self.events.append(event)
                if event["type"] == "error":
                    self.error = event.get("error")
                if event["type"] == "summary":
                    finished = True
                    break
            try:
                code = await asyncio.wait_for(self._proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                code = 0 if finished else -1
            if self.status == "stopped":
                return
            if code != 0 or self.error:
                self.status = "error"
                self.error = self.error or f"The replay stopped unexpectedly (exit code {code})."
                self._keep_log(workdir)
            else:
                self.status = "done"
                self._save()
        except asyncio.CancelledError:
            self.status = "stopped"
        except Exception as e:
            logger.error(f"Flow replay failed: {e}")
            self.status, self.error = "error", str(e)
        finally:
            self._kill_worker()
            shutil.rmtree(workdir, ignore_errors=True)

    def _keep_log(self, workdir: Path) -> None:
        try:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy(workdir / "worker.log", RESULTS_DIR / "flow_last_failed.log")
        except Exception:
            pass

    def _save(self) -> None:
        try:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            name = f"flow_{abs(int(self.params.get('channel_id', 0)))}_{stamp}.json"
            (RESULTS_DIR / name).write_text(json.dumps({"params": self.params, "events": self.events},
                                                       ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Flow replay: could not save the result: {e}")


from datetime import timedelta  # noqa: E402

_MARGIN = timedelta(minutes=90)            # chart context before the first and after the last message
flow_replay_service = FlowReplayService()
