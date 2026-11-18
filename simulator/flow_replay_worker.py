"""
Flow replay worker — replays real channel messages through the bot's real logic.

Runs in its OWN process with its own empty database and a simulated broker, so
nothing here can reach the live account, the live database or Telegram. The bot
process (simulator/flow_replay.py) starts it, gives it the fetched messages and
the bot's current settings, and answers its requests for price history.

Protocol (one JSON object per line):
  worker → parent on stdout, each line prefixed with "@@FLOW ":
      {"type": "started", ...}                 replay is running
      {"type": "need_symbol", "symbol": ...}   send me the spec and M1 bars
      {"type": "message", ...}                 one channel message and what the bot did
      {"type": "market", ...}                  what the broker did between two messages
      {"type": "summary", ...}                 totals; the replay is finished
      {"type": "error", "error": ...}
  parent → worker on stdin:
      {"symbol": ..., "spec": {...} | null, "bars": [[iso time, o, h, l, c], ...]}

Time: messages are delivered one after the other, not in real time. Before each
one everything already recorded is aged by the real gap to the previous message
(database timestamps, follow-up windows, duplicate windows), so "30 minutes
later" behaves as it did live. Prices between two messages come from the M1
history; without history a message's own price is used and nothing is filled
or stopped in between.
"""
import argparse
import asyncio
import bisect
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_OUT = sys.stdout


def emit(obj: dict) -> None:
    _OUT.write("@@FLOW " + json.dumps(obj, default=str) + "\n")
    _OUT.flush()


def parse_time(value) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# Settings the replay never takes from the live bot: they point at the live
# account, at Telegram, or need services that only run in the bot process.
FORCED = dict(
    trading_provider="mt5rest", dry_run=False, skip_metaapi=False, copy_master_mode=False,
    require_manual_approval=False, enable_trading_brain=False, enable_equity_protection=False,
    news_enable_filter=False, enable_signal_validator=False, enable_ai_market_analysis=False,
    mt5_symbol_suffix="", max_signal_age_minutes=5,
)


def bootstrap_environment(live: dict) -> None:
    """Environment the bot's settings are built from — before any bot module is imported."""
    port = os.environ.setdefault("SIM_BRIDGE_PORT", "5055")
    base = {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "sim", "TELEGRAM_PHONE": "+10000000000"}
    for key, value in base.items():
        os.environ.setdefault(key, value)
    os.environ.update({"TRADING_PROVIDER": "mt5rest", "DRY_RUN": "false", "SKIP_METAAPI": "false",
                       "MT5_REST_API_URL": f"http://127.0.0.1:{port}"})
    for key, value in (live.get("env") or {}).items():      # AI provider, models, keys
        if value not in (None, ""):
            os.environ[key] = str(value)


class Prices:
    """M1 history per symbol, fetched from the parent on first use."""

    def __init__(self, ask_parent):
        self._ask = ask_parent
        self.bars: Dict[str, Tuple[List[datetime], List[tuple]]] = {}
        self.specs: Dict[str, Optional[dict]] = {}

    async def load(self, symbol: str) -> Optional[dict]:
        if symbol not in self.specs:
            answer = await self._ask(symbol)
            times, rows = [], []
            for row in answer.get("bars") or []:
                times.append(parse_time(row[0]))
                rows.append(tuple(float(x) for x in row[1:5]))
            order = sorted(range(len(times)), key=times.__getitem__)
            self.bars[symbol] = ([times[i] for i in order], [rows[i] for i in order])
            self.specs[symbol] = answer.get("spec")
        return self.specs[symbol]

    def close_at(self, symbol: str, when: datetime) -> Optional[float]:
        times, rows = self.bars.get(symbol, ([], []))
        i = bisect.bisect_right(times, when) - 1
        return rows[i][3] if i >= 0 else None

    def path(self, symbol: str, start: datetime, end: datetime) -> List[Tuple[datetime, float]]:
        """Prices to walk through between two moments: each bar as open, the two extremes, close.
        The order inside a bar is not known; a falling bar is walked high first, a rising one low first."""
        times, rows = self.bars.get(symbol, ([], []))
        out = []
        for i in range(bisect.bisect_right(times, start), bisect.bisect_right(times, end)):
            o, h, l, c = rows[i]
            for price in ((o, h, l, c) if c < o else (o, l, h, c)):
                out.append((times[i], price))
        return out


def guess_price(text: str) -> Optional[float]:
    """A price to stand on when there is no history: the first price-like number in the message."""
    for token in re.findall(r"(?<![\w.])\d{1,7}(?:[.,]\d{1,5})?(?![\w%])", text or ""):
        value = float(token.replace(",", "."))
        if value >= 0.5 and not (1900 <= value <= 2100 and "." not in token and len(token) == 4 and value % 1 == 0
                                 and str(int(value)) in ("2024", "2025", "2026", "2027")):
            return value
    return None


async def run(args) -> None:
    live = json.load(open(args.settings))
    messages = json.load(open(args.messages))
    for m in messages:
        m["date"] = parse_time(m["date"])
    messages.sort(key=lambda m: (m["date"], m["id"]))
    bootstrap_environment(live)

    from loguru import logger
    logger.remove()
    captured_errors: List[str] = []
    logger.add(lambda record: captured_errors.append(record.record["message"][:300]), level="ERROR")
    if args.log:
        logger.add(args.log, level="DEBUG")

    import src.models  # noqa: F401
    from config import settings
    from simulator.fake_mt5_bridge import FakeMT5Bridge
    from simulator.session import Session, BASELINE
    from aiohttp import web

    # ── the bot's live settings, minus what must not be replayed ─────────────
    applied = {}
    for key, value in (live.get("settings") or {}).items():
        if hasattr(settings, key) and key not in FORCED and isinstance(value, (bool, int, float, str)):
            try:
                current = getattr(settings, key)
                if isinstance(current, Enum):
                    value = type(current)(value)
                setattr(settings, key, value)
                applied[key] = value
            except Exception:
                pass
    for key, value in {**FORCED, **(live.get("overrides") or {})}.items():
        setattr(settings, key, value)
        applied[key] = value
    settings.mt5_rest_api_url = f"http://127.0.0.1:{os.environ['SIM_BRIDGE_PORT']}"
    for key in list(BASELINE):                     # the session must not reset them to its test baseline
        BASELINE[key] = getattr(settings, key, BASELINE[key])

    # ── parent link: price history on request ────────────────────────────────
    loop = asyncio.get_running_loop()
    stdin_lock = asyncio.Lock()

    async def ask_parent(symbol: str) -> dict:
        async with stdin_lock:
            emit({"type": "need_symbol", "symbol": symbol,
                  "from": messages[0]["date"].isoformat() if messages else None,
                  "to": parse_time(args.until).isoformat() if args.until else None})
            line = await loop.run_in_executor(None, sys.stdin.readline)
            try:
                return json.loads(line) if line.strip() else {}
            except ValueError:
                return {}

    prices = Prices(ask_parent)
    clock = {"now": messages[0]["date"] if messages else datetime.now(timezone.utc), "text": ""}
    no_history: set = set()

    class ReplayBridge(FakeMT5Bridge):
        """The simulated broker, with instruments and prices loaded as the bot asks for them."""

        def __init__(self):
            super().__init__()
            self.symbols = {}
            self._in_tick = False

        # every fill and close carries the replay's time, not the time the replay ran
        def _deal(self, p, entry, price, volume, profit=0.0):
            super()._deal(p, entry, price, volume, profit)
            deal = self.deals[p["ticket"]][-1]
            deal["time"] = deal["time_msc"] = clock["now"].isoformat()
            deal["side"] = "BUY" if p["type"] == 0 else "SELL"
            if entry == "IN":
                deal["how"] = "pending order filled" if self._in_tick else "market"

        def _close(self, ticket, price, reason, volume=None):
            super()._close(ticket, price, reason, volume)
            self.deals[ticket][-1]["how"] = {"TP": "take profit", "SL": "stop loss", "bot": "closed by the bot",
                                             "manual": "closed by hand"}.get(reason, reason)

        def tick(self, bid, symbol="XAUUSD"):
            self._in_tick = True
            try:
                return super().tick(bid, symbol)
            finally:
                self._in_tick = False

        async def ensure(self, name: str) -> bool:
            if name in self.symbols:
                return True
            spec = await prices.load(name)
            if not spec:
                return False
            price = prices.close_at(name, clock["now"])
            if price is None:
                price = guess_price(clock["text"])
                no_history.add(name)
            if price is None:
                return False
            self.symbols[name] = dict(contract=float(spec.get("contract", 100000)), spread=float(spec.get("spread", 0)),
                                      digits=int(spec.get("digits", 5)), tick_value=float(spec.get("tick_value", 1)),
                                      bid=round(price, int(spec.get("digits", 5))))
            return True

        async def symbol_list(self, _):
            return web.json_response([])           # the provider then asks per instrument

        async def symbol_info(self, request):
            if not await self.ensure(request.match_info["s"]):
                return web.json_response({"error": f"Symbol {request.match_info['s']} NOT FOUND"}, status=404)
            return await super().symbol_info(request)

        async def tick_info(self, request):
            if not await self.ensure(request.match_info["s"]):
                return web.json_response({"error": f"No tick for symbol {request.match_info['s']} NOT FOUND"}, status=404)
            return await super().tick_info(request)

    bridge = ReplayBridge()
    trace: List[str] = []
    s = Session(out=trace.append, bridge=bridge)
    await s.start()

    from src.services.signal_service import signal_service
    from src.services.signal_continuity import signal_continuity
    from src.services.reply_handler_service import reply_handler_service
    from src.core.database_service import db_service
    try:
        from ai.trade_command_processor import TradeCommandProcessor
        reply_handler_service.ai_processor = TradeCommandProcessor(settings)   # built at import with the old settings
    except Exception as e:
        captured_errors.append(f"reply AI not available: {e}")

    # ── what the bot understood: recorded as it happens ──────────────────────
    cap: dict = {}

    def wrap(obj, name, record):
        original = getattr(obj, name)

        async def wrapper(*a, **k):
            result = await original(*a, **k)
            try:
                record(result, a, k)
            except Exception:
                pass
            return result
        setattr(obj, name, wrapper)

    def signal_view(sig) -> Optional[dict]:
        if sig is None:
            return None
        return {"symbol": sig.symbol, "side": getattr(getattr(sig, "order_type", None), "value", None),
                "action": getattr(getattr(sig, "action", None), "value", None),
                "entry": sig.entry_price, "entries": getattr(sig, "entries", None),
                "zone": [sig.entry_range_min, sig.entry_range_max] if getattr(sig, "entry_range_min", None) else None,
                "sl": sig.stop_loss, "tps": list(sig.take_profit or []),
                "instant": bool(getattr(sig, "instant_execution", False)), "plan": bool(getattr(sig, "is_plan", False))}

    def on_extract(result, a, k):
        found = result if isinstance(result, list) else [result]
        cap.setdefault("parsed", []).extend(v for v in (signal_view(x) for x in found) if v)
        if not any(found):
            reason = getattr(getattr(signal_service, "processor", None), "rejection_reason", None)
            if reason:
                cap["not_parsed"] = str(reason)[:200]

    wrap(signal_service, "classify_intent", lambda r, a, k: cap.__setitem__("intent", r))
    wrap(signal_service, "extract_signal", on_extract)
    wrap(signal_continuity, "find_parent", lambda r, a, k: cap.__setitem__(
        "relation", {"to_message": r[0].messageId, "why": r[1]}) if r and r[0] is not None else None)
    wrap(reply_handler_service, "handle_reply", lambda r, a, k: cap.__setitem__("command", {
        "target_message": k.get("reply_to_message_id", a[0] if a else None),
        "success": bool((r or {}).get("success")), "ignored": bool((r or {}).get("ignored")),
        "result": ((r or {}).get("message") or (r or {}).get("error") or "")[:240]}))
    if getattr(reply_handler_service, "ai_processor", None) is not None:
        wrap(reply_handler_service.ai_processor, "process_command", lambda r, a, k: cap.__setitem__("ai_action", {
            "action": getattr(r, "action", None), "value": getattr(r, "value", None),
            "percentage": getattr(r, "percentage", None)} if r is not None else {"action": None}))

    # ── ageing: make "now" later without waiting ─────────────────────────────
    date_columns: List[Tuple[str, str]] = []
    for row in await s.prisma.client.query_raw("SELECT name FROM sqlite_master WHERE type='table'"):
        for col in await s.prisma.client.query_raw(f'PRAGMA table_info("{row["name"]}")'):
            if str(col.get("type", "")).upper() == "DATETIME":
                date_columns.append((row["name"], col["name"]))

    async def age(seconds: float) -> List[str]:
        """Everything recorded so far becomes `seconds` older. Returns what ran out meanwhile."""
        if seconds <= 0:
            return []
        ms = int(seconds * 1000)
        for table, column in date_columns:
            await s.prisma.client.execute_raw(
                f'UPDATE "{table}" SET "{column}" = "{column}" - {ms} WHERE "{column}" IS NOT NULL')
        shift = timedelta(seconds=seconds)
        handler = s.message_handler
        handler.recent_messages = {k: v - shift for k, v in handler.recent_messages.items()}
        signal_continuity._deleted = {k: (sid, t - seconds) for k, (sid, t) in signal_continuity._deleted.items()}
        expired = []
        for signal_id in list(signal_continuity._awaiting):
            signal_continuity._awaiting[signal_id] -= seconds
            if signal_continuity._awaiting[signal_id] <= time.monotonic():
                signal_continuity._awaiting.pop(signal_id, None)
                expired.append("no follow-up with the real SL / TP arrived in time — the instant entry keeps "
                               "its temporary SL")
        return expired

    # ── helpers ──────────────────────────────────────────────────────────────
    title = live.get("channel_name") or str(live.get("channel_id"))
    channel = s.channel(title, chat_id=int(live["channel_id"]))
    log_mark = {"n": 0}

    def broker_lines() -> List[str]:
        lines = bridge.log[log_mark["n"]:]
        log_mark["n"] = len(bridge.log)
        return lines

    def bot_notes() -> List[str]:
        notes = [n for n in s._notes]
        s._notes.clear()
        s._seen_log = len(bridge.log)
        return notes

    def setup() -> List[dict]:
        rows = []
        for p in bridge.positions.values():
            rows.append({"ticket": p["ticket"], "state": "open", "symbol": p["symbol"],
                         "side": "BUY" if p["type"] == 0 else "SELL", "lots": p["volume"], "entry": p["price_open"],
                         "sl": p["sl"] or None, "tp": p["tp"] or None, "pnl": bridge._profit(p), "signal": p["magic"]})
        for o in bridge.orders.values():
            rows.append({"ticket": o["ticket"], "state": "pending", "symbol": o["symbol"],
                         "side": "BUY" if o["type"] in (2, 4) else "SELL", "lots": o["volume_current"],
                         "entry": o["price_open"], "sl": o["sl"] or None, "tp": o["tp"] or None, "pnl": None,
                         "signal": o["magic"]})
        return sorted(rows, key=lambda r: r["ticket"])

    def realized() -> float:
        return round(sum(c["profit"] for c in bridge.closed), 2)

    sent_deals: set = set()

    def new_executions() -> List[dict]:
        """Fills and closes since the last call, in time order."""
        rows = []
        for ticket, deals in bridge.deals.items():
            for d in deals:
                if d["ticket"] in sent_deals:
                    continue
                sent_deals.add(d["ticket"])
                rows.append({"time": d["time"], "ticket": ticket, "signal": d["magic"], "symbol": d["symbol"],
                             "side": d.get("side"), "kind": "entry" if d["entry"] == "IN" else "exit",
                             "how": d.get("how") or "", "lots": d["volume"], "price": d["price"],
                             "pnl": d["profit"] if d["entry"] == "OUT" else None})
        return sorted(rows, key=lambda r: (r["time"], r["ticket"]))

    async def walk_market(start: datetime, end: datetime, after_message: Optional[int]) -> None:
        """Replay prices between two messages for every instrument that has something open."""
        active = sorted({p["symbol"] for p in bridge.positions.values()} | {o["symbol"] for o in bridge.orders.values()})
        steps = sorted((t, price, sym) for sym in active for t, price in prices.path(sym, start, end))
        events, since_sync = [], 0
        for t, price, sym in steps[: args.max_steps]:
            clock["now"] = t
            happened = bridge.tick(price, sym)
            since_sync += 1
            if happened or since_sync >= args.sync_every:
                clock["now"] = t
                await s.sync()
                since_sync = 0
                for line in happened:
                    events.append({"time": t.isoformat(), "text": line, "by": "broker"})
                for line in broker_lines():
                    events.append({"time": t.isoformat(), "text": line, "by": "bot"})
                for line in bot_notes():
                    events.append({"time": t.isoformat(), "text": line, "by": "note"})
            if not bridge.positions and not bridge.orders:
                break
        if steps:
            await s.sync()
            for line in broker_lines():
                events.append({"time": end.isoformat(), "text": line, "by": "bot"})
            bot_notes()
        clock["now"] = end
        for sym in bridge.symbols:                      # everything stands at the price of the next message
            price = prices.close_at(sym, end)
            if price is not None:
                for line in bridge.tick(price, sym):
                    events.append({"time": end.isoformat(), "text": line, "by": "broker"})
        if events:
            await s.sync()
            bot_notes()
            broker_lines()
            emit({"type": "market", "after_message": after_message, "events": events, "setup": setup(),
                  "realized": realized(), "executions": new_executions()})

    emit({"type": "started", "messages": len(messages), "channel": title,
          "runner": bool(settings.enable_runner_split), "risk_percent": settings.max_risk_per_trade_percent,
          "ai": f"{settings.primary_ai_provider.value}"})

    # ── the replay ───────────────────────────────────────────────────────────
    counts = {"messages": 0, "signals": 0, "acted": 0, "ignored": 0, "review": 0}
    previous: Optional[dict] = None
    for index, m in enumerate(messages, 1):
        text = m.get("text") or ""
        notes_before: List[str] = []
        if previous is not None:
            await walk_market(previous["date"], m["date"], previous["id"])
            notes_before = await age((m["date"] - previous["date"]).total_seconds())
        clock["now"], clock["text"] = m["date"], text
        cap.clear()
        captured_errors.clear()
        broker_lines()
        bot_notes()

        event_kind = m.get("event") or "post"        # scripted histories can also edit and delete
        if event_kind == "delete":
            detail = f"the channel deleted message #{m['target']}"
            try:
                await channel.delete(int(m["target"]))
            except Exception as e:
                captured_errors.append(f"{type(e).__name__}: {e}")
            outcome, review = None, []
        elif event_kind == "edit":
            detail = f"the channel edited message #{m['target']}"
            try:
                await channel.edit(int(m["target"]), text)
            except Exception as e:
                captured_errors.append(f"{type(e).__name__}: {e}")
            outcome, review = None, []
        elif not text.strip():
            outcome, review = "SKIPPED", []
            detail = "image or media without text — not replayed" if m.get("media") else "empty message"
        else:
            detail = None
            try:
                await channel.post(text, reply_to=m.get("reply_to"), msg_id=int(m["id"]))
            except Exception as e:
                captured_errors.append(f"{type(e).__name__}: {e}")
            outcome, review = None, []

        actions, notes = broker_lines(), notes_before + bot_notes()
        if outcome is None:
            kinds = {line.split(" ", 1)[0] for line in actions}
            intent = cap.get("intent") or ("COMMAND" if m.get("reply_to") or cap.get("command") else None)
            if kinds & {"MARKET", "PENDING"}:
                outcome = "MERGED" if cap.get("relation") else "ENTERED"
            elif "CLOSE" in kinds:
                outcome = "CLOSED"
            elif "CANCEL" in kinds:
                outcome = "CANCELLED"
            elif "MODIFY" in kinds:
                outcome = "UPDATED"
            elif cap.get("relation"):
                outcome = "MERGED"
            elif cap.get("parsed") and any(p.get("plan") for p in cap["parsed"]):
                outcome = "PLAN"
            elif any("approval request" in n for n in notes):
                outcome = "NEEDS APPROVAL"          # the bot's safety gate asked the owner; nothing was entered
            elif event_kind != "post":
                outcome = "NO ACTION"
            elif cap.get("parsed") or intent == "SIGNAL":
                outcome = "REJECTED"
            else:
                outcome = "NO ACTION"
            # what a person should look at
            if outcome == "REJECTED":
                reason = next((n for n in notes if "rejected" in n.lower()), cap.get("not_parsed") or "")
                review.append(f"read as a signal but not traded{': ' + reason[:160] if reason else ''}")
            command = cap.get("command") or {}
            if command and not command.get("success") and not command.get("ignored") and command.get("result"):
                review.append(f"command not carried out: {command['result'][:160]}")
            if cap.get("intent") == "COMMAND" and not actions and not command:
                review.append("read as a command but nothing was running to manage")
            if "not closed" in (command.get("result") or ""):
                review.append("partial close: positions at the minimum lot cannot be split — they were kept "
                              + ("and moved to break-even instead of being closed"
                                 if "break-even" in command["result"] else "as they are"))
            for name in sorted(no_history):
                review.append(f"no price history for {name}: entered at the message's own price, "
                              f"no fills or stops replayed in between")
            no_history.clear()
            for err in captured_errors[:3]:
                review.append(f"error in the bot: {err[:160]}")

        counts["messages"] += 1
        counts["signals"] += outcome in ("ENTERED", "PLAN")
        counts["acted"] += outcome in ("MERGED", "CLOSED", "CANCELLED", "UPDATED")
        counts["ignored"] += outcome in ("NO ACTION", "SKIPPED")
        if outcome == "NEEDS APPROVAL":
            review.append("held for the owner's approval by the bot's safety gate — not entered in the replay")
        counts["review"] += bool(review)
        quote = lambda sym: {"bid": bridge.bid_of(sym), "ask": bridge.ask_of(sym)}  # noqa: E731
        emit({
            "type": "message", "index": index, "total": len(messages), "id": m["id"],
            "date": m["date"].isoformat(), "text": text, "reply_to": m.get("reply_to"),
            "edited": bool(m.get("edited")), "media": bool(m.get("media")),
            "event": event_kind, "target": m.get("target"),
            "intent": cap.get("intent") or ("REPLY" if m.get("reply_to") else "COMMAND" if cap.get("command")
                                            else None),
            "parsed": cap.get("parsed") or [], "not_parsed": cap.get("not_parsed"),
            "relation": cap.get("relation"), "command": cap.get("command"), "ai_action": cap.get("ai_action"),
            "outcome": outcome, "detail": detail, "actions": actions, "notes": notes, "review": review,
            "prices": {sym: quote(sym) for sym in bridge.symbols}, "setup": setup(), "realized": realized(),
            "executions": new_executions(), "counts": dict(counts),
        })
        previous = m

    # ── after the last message: let what is open play out to the end of the window ──
    if previous is not None and args.until:
        await walk_market(previous["date"], parse_time(args.until), previous["id"])
    # price bars for the charts: every instrument that was traded, over the whole window
    window_start = messages[0]["date"] - timedelta(minutes=90) if messages else None
    window_end = (parse_time(args.until) if args.until else previous["date"]) + timedelta(minutes=30) if previous else None
    for sym in sorted({d["symbol"] for deals in bridge.deals.values() for d in deals}
                      | {o["symbol"] for o in bridge.orders.values()}):
        times, rows = prices.bars.get(sym, ([], []))
        lo, hi = bisect.bisect_left(times, window_start), bisect.bisect_right(times, window_end)
        step_n = max(1, (hi - lo) // 3000 + (1 if (hi - lo) % 3000 else 0)) if hi - lo > 3000 else 1
        bars = []
        for i in range(lo, hi, step_n):                 # long windows: several minutes per candle
            chunk = rows[i:min(i + step_n, hi)]
            bars.append([times[i].isoformat(), chunk[0][0], max(r[1] for r in chunk), min(r[2] for r in chunk),
                         chunk[-1][3]])
        emit({"type": "chart", "symbol": sym, "minutes_per_bar": step_n, "bars": bars})

    open_now = setup()
    floating = round(sum(r["pnl"] or 0 for r in open_now), 2)
    signals = []
    for sig in await db_service.db.signal.find_many(order={"createdAt": "asc"}, include={"trades": True}):
        signals.append({"message": sig.messageId, "symbol": sig.symbol, "side": sig.orderType, "status": sig.status,
                        "trades": len(sig.trades), "pnl": round(sum(t.profitLoss or 0 for t in sig.trades), 2)})
    emit({"type": "summary", "counts": counts, "realized": realized(), "floating": floating, "open": open_now,
          "executions": new_executions(),
          "signals": signals, "settings": {k: applied[k] for k in sorted(applied)
                                           if k in ("max_risk_per_trade_percent", "enable_runner_split",
                                                    "runner_share_percent", "enable_breakeven_move",
                                                    "breakeven_trigger_method", "enable_trailing_stop",
                                                    "enable_auto_partial", "enable_instant_execution")}})
    # The result is out. Shut down briefly, then leave: the database engine child does
    # not always exit when its pipes are held by the parent, and nothing here is kept.
    try:
        await asyncio.wait_for(s.stop(), timeout=5)
    except Exception:
        pass
    _OUT.flush()
    os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--messages", required=True, help="JSON file: [{id, date, text, reply_to, edited, media}]")
    parser.add_argument("--settings", required=True, help="JSON file: {channel_id, channel_name, env, settings, overrides}")
    parser.add_argument("--until", help="replay prices after the last message until this time (ISO)")
    parser.add_argument("--log", help="write the bot's debug log here")
    parser.add_argument("--max-steps", type=int, default=20000, help="price steps replayed between two messages")
    parser.add_argument("--sync-every", type=int, default=20, help="run order sync / monitor at least every N price steps")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as e:
        import traceback
        emit({"type": "error", "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]})
        sys.exit(1)


if __name__ == "__main__":
    main()
