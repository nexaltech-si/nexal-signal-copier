"""
Simulated session at the message level: Telegram posts in, orders out.

Channel messages (new post, reply, edit, delete) are built as Telethon events
and handed to the bot's real message handler — the same three calls the
Telegram listener makes. From there everything is the live code: intent
classification, signal extraction and reply parsing by the configured AI
provider, follow-up / repost matching, risk sizing, the MT5 REST provider,
order sync and the position monitor, on a real database.

Only two things are replaced:
  • Telegram   — messages come from the script below; the bot's own
                 notifications are printed instead of sent
  • the broker — simulator/fake_mt5_bridge.py answers the MT5 bridge's HTTP API

Needs an AI key for the provider in PRIMARY_AI_PROVIDER (default here: deepseek).

    DATABASE_URL=file:/path/sim.db DEEPSEEK_API_KEY=... python scripts/simulate_message_flow.py

Prints, per message, what the bot detected and what it sent to the broker, then
a PASS / FAIL line per check. Exit code 1 when a check failed.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIDGE_PORT = int(os.environ.get("SIM_BRIDGE_PORT", "5055"))
for key, value in {
    "TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "sim", "TELEGRAM_PHONE": "+10000000000",
    "PRIMARY_AI_PROVIDER": "deepseek", "FALLBACK_AI_PROVIDERS": "", "DEEPSEEK_MODEL": "deepseek-flash",
    "TRADING_PROVIDER": "mt5rest", "MT5_REST_API_URL": f"http://127.0.0.1:{BRIDGE_PORT}",
    "DRY_RUN": "false", "SKIP_METAAPI": "false",
}.items():
    os.environ.setdefault(key, value)

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level=os.environ.get("SIM_LOG_LEVEL", "ERROR"))
if os.environ.get("SIM_LOG_FILE"):
    logger.add(os.environ["SIM_LOG_FILE"], level="DEBUG")

import src.models  # noqa: E402,F401
from config import settings  # noqa: E402
from simulator.fake_mt5_bridge import FakeMT5Bridge  # noqa: E402

CHANNEL_ID = -1001234567890
CHANNEL_TITLE = "SIGNAL CHANNEL (simulated)"
checks = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok)))
    print(f"   {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}", flush=True)


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(4, 74 - len(title)), flush=True)


class Channel:
    """The Telegram side: builds the events Telethon would deliver for a channel."""

    def __init__(self, first_id: int = 35144):
        self.next_id = first_id
        self.posts = {}

    def _event(self, msg_id: int, text: str, reply_to=None, edited: bool = False):
        now = datetime.now(timezone.utc)
        chat = SimpleNamespace(id=CHANNEL_ID, title=CHANNEL_TITLE, username=None)
        message = SimpleNamespace(
            id=msg_id, chat_id=CHANNEL_ID, text=text, message=text, raw_text=text,
            date=self.posts.get(msg_id, {}).get("date", now), edit_date=now if edited else None,
            sender_id=CHANNEL_ID, sender=chat, from_id=None, post=True, out=False,
            reply_to=SimpleNamespace(reply_to_msg_id=reply_to) if reply_to else None,
            media=None, photo=None, grouped_id=None, fwd_from=None, entities=None,
        )

        async def get_chat():
            return chat
        return SimpleNamespace(message=message, chat_id=CHANNEL_ID, get_chat=get_chat, chat=chat)

    def post(self, text: str, reply_to=None):
        msg_id, self.next_id = self.next_id, self.next_id + 1
        self.posts[msg_id] = {"text": text, "date": datetime.now(timezone.utc)}
        return msg_id, self._event(msg_id, text, reply_to)

    def edit(self, msg_id: int, text: str):
        self.posts[msg_id]["text"] = text
        return self._event(msg_id, text, edited=True)

    @staticmethod
    def delete(msg_id: int):
        return SimpleNamespace(chat_id=CHANNEL_ID, deleted_ids=[msg_id])


async def main() -> int:
    from src.core.prisma_client import prisma_client
    from src.core.database_service import db_service
    from src.integrations.telegram.unified_sender import notification_sender
    from src.integrations.trading.provider_manager import provider_manager
    from src.services.message_handler import message_handler
    from src.services.trading_service import trading_service
    from src.services.signal_continuity import signal_continuity
    from src.services.signal_service import signal_service
    from src.services.magic_number_service import magic_number_service
    from src.services.order_sync_service import order_sync_service
    from src.services.position_monitor_service import position_monitor_service

    bridge = FakeMT5Bridge(bid=3947.5, balance=10000.0)
    await bridge.start(BRIDGE_PORT)
    for key, value in dict(
        max_risk_per_trade_percent=1.0, enable_trading_brain=False, enable_equity_protection=False,
        require_manual_approval=False, enable_signal_validator=False, copy_master_mode=False,
        enable_instant_execution=True, min_lot_size=0.01, news_enable_filter=False,
        enable_runner_split=True, runner_share_percent=50.0,
        # position monitor: auto take profit on, profit-based SL rules off — every SL move
        # below comes from a channel message
        enable_auto_take_profit=True, enable_auto_partial=False, enable_trailing_stop=False,
        enable_breakeven_move=False, enable_ai_market_analysis=False,
    ).items():
        setattr(settings, key, value)

    # ── the bot's own Telegram notifications are printed, not sent ───────────
    notes = []

    def note(text: str) -> None:
        import re
        line = re.sub(r"<[^>]+>", "", str(text)).strip().replace("\n", " | ")
        notes.append(line)

    async def send_message(message, *a, **k):
        note(message)

    def named(name):
        async def notify(*args, **kw):
            sig = next((a for a in args if hasattr(a, "symbol")), None)
            extra = next((a for a in args if isinstance(a, str)), "")
            what = name.replace("notify_", "").replace("_", " ")
            note(f"[{what}] {getattr(sig, 'symbol', '') or ''} "
                 f"{getattr(getattr(sig, 'order_type', None), 'value', '') or ''} {extra}".strip())
        return notify
    notification_sender.send_message = send_message
    for name in dir(notification_sender):
        if name.startswith("notify_"):
            setattr(notification_sender, name, named(name))

    await prisma_client.initialize()
    await provider_manager.start()
    provider = provider_manager.proxy
    trading_service.set_trading_provider(provider)
    signal_service.reinitialize()
    channel = Channel()
    print(f"AI provider: {settings.primary_ai_provider.value} ({settings.deepseek_model})  |  broker: simulated MT5 bridge  |  "
          f"runner: {'ON' if settings.enable_runner_split else 'OFF'} ({settings.runner_share_percent:.0f}%)")

    # ── helpers ──────────────────────────────────────────────────────────────
    seen = {"log": 0}

    async def sync() -> None:
        provider._positions_cache = provider._orders_cache = None
        for _ in range(order_sync_service.CLOSE_GRACE_MISSES + 1):
            await order_sync_service.sync_all_active_orders()
        provider._positions_cache = None
        await position_monitor_service._check_all_positions()
        provider._positions_cache = provider._orders_cache = None

    def report() -> None:
        """What the bot said and what it sent to the broker since the last report."""
        for line in notes:
            print(f"      bot: {line[:230]}")
        notes.clear()
        for line in bridge.log[seen["log"]:]:
            print(f"      broker ← {line}")
        seen["log"] = len(bridge.log)

    async def deliver(label: str, coro) -> None:
        print(f"   {label}", flush=True)
        await coro
        await asyncio.sleep(0.3)             # fire-and-forget tasks (marks, forwards)
        await sync()
        report()

    async def post(text: str, reply_to=None) -> int:
        msg_id, event = channel.post(text, reply_to)
        shown = text.replace("\n", " / ")
        await deliver(f"channel #{msg_id}{f' (reply to #{reply_to})' if reply_to else ''}: \"{shown}\"",
                      message_handler.process_message(event, trading_service.process_signal))
        return msg_id

    async def edit(msg_id: int, text: str) -> None:
        shown = text.replace("\n", " / ")
        await deliver(f"channel EDITS #{msg_id}: \"{shown}\"",
                      message_handler.process_edited_message(channel.edit(msg_id, text), trading_service.process_signal))

    async def delete(msg_id: int) -> None:
        await deliver(f"channel DELETES #{msg_id}", message_handler.process_deleted_messages(channel.delete(msg_id)))

    async def tick(bid: float) -> None:
        events = bridge.tick(bid)
        print(f"   market → bid {bid}" + "".join(f"\n      broker: {e}" for e in events), flush=True)
        await sync()
        report()

    async def live(msg_id: int):
        magic = magic_number_service.generate_magic_number(msg_id)
        return sorted(await signal_continuity._live_orders({magic}, False), key=lambda o: o["id"])

    def show(orders) -> None:
        for o in orders:
            kind = "pending " if o["pending"] else "position"
            print(f"      {kind} #{o['id']}  {o['volume']:.2f} lots @ {o['openPrice']}  "
                  f"SL {o['stopLoss']}  TP {o['takeProfit'] or '— none (runner)'}")
        if not orders:
            print("      (no open orders)")

    async def record(msg_id: int):
        sig = await db_service.db.signal.find_first(where={"channelId": str(CHANNEL_ID), "messageId": msg_id},
                                                    include={"trades": True})
        return sig, (sig.trades if sig else [])

    def writes() -> int:
        return len(bridge.log)

    # ── A. the channel's real sequence: instant entry, then the levels ───────
    step("A. \"GOLD SELL NOW\", then the levels, then chatter")
    first = await post("GOLD SELL NOW")
    orders = await live(first)
    show(orders)
    check("\"GOLD SELL NOW\" detected as an instant SELL: one position on a temporary SL",
          len(orders) == 1 and not orders[0]["pending"] and orders[0]["stopLoss"])

    follow = await post("GOLD SELL NOW\n @ 3948\n\nTP : 3933\nTP : 3910\n\nSL : 3966")
    orders = await live(first)
    show(orders)
    parent, trades = await record(first)
    copy, _ = await record(follow)
    check("follow-up recognised: no second signal", copy is None)
    check("all orders are trades of the first signal", parent and len(trades) == len(orders),
          f"{len(trades)} trades, {len(orders)} orders")
    check("levels read correctly: SL 3966, TP 3933 / 3910",
          parent and abs((parent.stopLoss or 0) - 3966) < 0.5 and "3933" in (parent.takeProfit or "")
          and "3910" in (parent.takeProfit or ""), f"SL {parent.stopLoss} TP {parent.takeProfit}" if parent else "")
    check("every order on the real SL", orders and all(abs(o["stopLoss"] - 3966) <= 0.5 for o in orders))
    check("one runner without TP among the added orders", sum(1 for o in orders if not o["takeProfit"]) == 1)

    before = writes()
    await post("Enter now", reply_to=first)
    await post("Running!", reply_to=follow)
    await post("Don’t rush! if by chance it move up we will take 1 more entry on better price just wait "
               "for update, and keep hold 3948 with given TP - SL", reply_to=follow)
    await tick(3948.2)
    await tick(3940.0)
    before = writes()
    await post("On its way", reply_to=follow)
    await post("80 pips now 🫣✅", reply_to=follow)
    check("status chatter changed nothing at the broker", writes() == before,
          "; ".join(bridge.log[before:]))
    signals = await db_service.db.signal.count(where={"channelId": str(CHANNEL_ID)})
    check("still exactly one signal in the database", signals == 1, f"{signals} signals")

    step("A2. TP1 is hit, channel says break-even, TP2 is hit, channel closes the rest")
    await tick(3932.5)
    await post("TP1 done ✅ set breakeven now", reply_to=follow)
    orders = await live(first)
    show(orders)
    open_now = [o for o in orders if not o["pending"]]
    check("break-even applied to every open position, runner included",
          open_now and all(o["stopLoss"] <= o["openPrice"] + 0.01 for o in open_now))
    check("runner still has no TP", any(not o["takeProfit"] for o in orders))
    await tick(3909.5)
    orders = await live(first)
    show(orders)
    check("after TP2 only the runner is left", len(orders) == 1 and not orders[0]["takeProfit"])
    await tick(3902.0)
    await post("Close all now, 460 pips ✅✅", reply_to=follow)
    orders = await live(first)
    show(orders)
    check("runner closed by the channel's message", not orders)
    parent, trades = await record(first)
    check("database: signal closed, every trade closed",
          parent.status == "CLOSED" and all(t.status == "CLOSED" for t in trades),
          f"signal {parent.status}; " + ", ".join(f"{t.status} {t.profitLoss}" for t in trades))
    runner_close = bridge.closed[-1]
    check("runner banked more than TP2 would have", runner_close["price_close"] < 3910.0,
          f"closed at {runner_close['price_close']}, {runner_close['profit']:+.2f}")

    # ── B. a complete signal, then an edit ───────────────────────────────────
    step("B. A complete signal in one message, then the channel edits its SL")
    await tick(3920.0)
    full = await post("XAUUSD BUY 3915\n\nSL 3900\nTP1 3925\nTP2 3940")
    orders_b = sorted(await signal_continuity._live_orders(
        {magic_number_service.generate_magic_number(full)}, True), key=lambda o: o["id"])
    show(orders_b)
    check("BUY detected with its levels: TP orders at 3925 / 3940 plus one runner",
          sorted(o["takeProfit"] for o in orders_b if o["takeProfit"]) == [3925.0, 3940.0]
          and sum(1 for o in orders_b if not o["takeProfit"]) == 1)
    await edit(full, "XAUUSD BUY 3915\n\nSL 3895\nTP1 3925\nTP2 3940")
    orders_b = sorted(await signal_continuity._live_orders(
        {magic_number_service.generate_magic_number(full)}, True), key=lambda o: o["id"])
    show(orders_b)
    check("edit applied: SL 3895 on every order, runner still without TP",
          orders_b and all(abs(o["stopLoss"] - 3895) <= 0.5 for o in orders_b)
          and sum(1 for o in orders_b if not o["takeProfit"]) == 1)
    check("edit created no second signal",
          await db_service.db.signal.count(where={"channelId": str(CHANNEL_ID)}) == 2)

    step("B2. The channel deletes the signal before it fills")
    await delete(full)
    orders_b = await signal_continuity._live_orders({magic_number_service.generate_magic_number(full)}, True)
    show(orders_b)
    check("pending orders cancelled when the signal was deleted", not orders_b)

    # ── C. messages that are not trades ──────────────────────────────────────
    step("C. Messages that must not open a trade")
    before, count = writes(), await db_service.db.signal.count(where={"channelId": str(CHANNEL_ID)})
    await post("Good morning traders ☀️ big news today at 15:30, stay ready and manage your risk")
    await post("Yesterday's result: +460 pips on GOLD 🔥 Join VIP for more signals")
    await post("Gold is looking bearish below 3950, I am waiting for a clean setup before any entry")
    check("no order sent for commentary / promotion / analysis", writes() == before,
          "; ".join(bridge.log[before:]))

    # ── D. management actions on a running setup with a runner ───────────────
    step("D. A pending setup is cancelled by the channel")
    await tick(3955.0)
    pending_id = await post("SELL LIMIT GOLD 3962\n\nSL 3980\nTP 3950\nTP 3935\nTP 3920")
    orders = await live(pending_id)
    show(orders)
    check("limit setup placed as pending orders: 3950 / 3935 / 3920 plus one runner",
          orders and all(o["pending"] for o in orders)
          and sorted({o["takeProfit"] for o in orders if o["takeProfit"]}) == [3920.0, 3935.0, 3950.0]
          and sum(1 for o in orders if not o["takeProfit"]) == 1)
    await post("Cancel the limit orders, we will enter later", reply_to=pending_id)
    orders = await live(pending_id)
    show(orders)
    check("\"Cancel the limit orders\": every pending order cancelled, runner included", not orders)

    step("D2. A running setup with a runner: SL moves, partial close, trailing, stop-out")
    d = await post("SELL GOLD NOW\n\nSL 3975\nTP 3945\nTP 3930\nTP 3915")

    async def setup():
        orders = await live(d)
        show(orders)
        return orders, [o for o in orders if not o["takeProfit"]], [o for o in orders if o["takeProfit"]]

    orders, runner, on_tp = await setup()
    check("setup filled at market: positions on 3945 / 3930 / 3915 plus one runner",
          orders and all(not o["pending"] for o in orders) and len(runner) == 1
          and sorted({o["takeProfit"] for o in on_tp}) == [3915.0, 3930.0, 3945.0])

    await post("Move SL to 3970", reply_to=d)
    orders, runner, on_tp = await setup()
    check("\"Move SL to 3970\": on every position, runner included; runner still without TP",
          orders and all(abs(o["stopLoss"] - 3970) <= 0.5 for o in orders) and len(runner) == 1)

    await tick(3944.5)
    orders, runner, on_tp = await setup()
    check("TP1 hit: only the 3945 position closed",
          len(runner) == 1 and sorted({o["takeProfit"] for o in on_tp}) == [3915.0, 3930.0])
    lots_before = round(sum(o["volume"] for o in orders), 2)
    runner_before = runner[0]["volume"] if runner else 0

    await post("Close half and hold the rest 🔥", reply_to=d)
    orders, runner, on_tp = await setup()
    lots_now = round(sum(o["volume"] for o in orders), 2)
    check("\"Close half\": lots reduced, the runner is still running without TP",
          0 < lots_now < lots_before and len(runner) == 1,
          f"{lots_before} → {lots_now} lots; runner {runner_before} → {runner[0]['volume'] if runner else 0}")

    await post("SL to entry", reply_to=d)
    orders, runner, on_tp = await setup()
    check("\"SL to entry\": break-even on every open position, runner included",
          orders and all(o["stopLoss"] <= o["openPrice"] + 0.01 for o in orders) and len(runner) == 1)

    await tick(3929.5)
    await tick(3914.5)
    orders, runner, on_tp = await setup()
    check("remaining TPs hit: only the runner is left", len(orders) == 1 and len(runner) == 1)

    await post("Trail SL to 3930 and let it run 🚀", reply_to=d)
    orders, runner, on_tp = await setup()
    check("\"Trail SL to 3930\": runner SL locked in profit, still no TP",
          len(orders) == 1 and abs(orders[0]["stopLoss"] - 3930) <= 0.5 and not orders[0]["takeProfit"])

    await tick(3900.0)
    await tick(3930.5)
    orders, runner, on_tp = await setup()
    check("price comes back: runner stopped out in profit at its trailed SL",
          not orders and bridge.closed[-1]["reason"] == "SL" and bridge.closed[-1]["profit"] > 0,
          f"{bridge.closed[-1]['profit']:+.2f} at {bridge.closed[-1]['price_close']}")
    parent, trades = await record(d)
    check("database: signal closed, every trade closed with its result",
          parent is not None and parent.status == "CLOSED" and all(t.status == "CLOSED" for t in trades),
          (f"signal {parent.status}; " + ", ".join(f"{t.status} {t.profitLoss}" for t in trades)) if parent else "no record")

    # ── E. commands that are not replies ─────────────────────────────────────
    step("E. Management sent as a plain post, not as a reply")
    await tick(3930.0)
    e = await post("BUY GOLD 3928\nSL 3915\nTP 3938\nTP 3950")
    await tick(3927.5)
    await tick(3934.0)
    orders = sorted(await signal_continuity._live_orders({magic_number_service.generate_magic_number(e)}, True),
                    key=lambda o: o["id"])
    show(orders)
    await post("B.E")
    orders = sorted(await signal_continuity._live_orders({magic_number_service.generate_magic_number(e)}, True),
                    key=lambda o: o["id"])
    show(orders)
    check("plain \"B.E\" post: break-even on the channel's running setup, runner included",
          orders and all(o["stopLoss"] >= o["openPrice"] - 0.01 for o in orders)
          and any(not o["takeProfit"] for o in orders))
    await post("Close gold now, news coming")
    orders = await signal_continuity._live_orders({magic_number_service.generate_magic_number(e)}, True)
    show(orders)
    check("plain \"Close gold now\" post: everything closed, runner included", not orders)
    _, trades = await record(e)
    check("database: the BUY closed in profit is recorded with positive pips",
          trades and all((t.profitLoss or 0) > 0 and (t.profitLossPips or 0) > 0 for t in trades),
          ", ".join(f"{t.profitLoss} / {t.profitLossPips} pips" for t in trades))

    # ── result ───────────────────────────────────────────────────────────────
    unhandled = [line for line in bridge.log if line.startswith("??")]
    check("no request the simulated broker could not answer", not unhandled, "; ".join(unhandled))
    failed = [name for name, ok in checks if not ok]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed" +
          ("" if not failed else "\nFAILED:\n" + "\n".join(f"  • {n}" for n in failed)), flush=True)
    await provider_manager.stop()
    if getattr(provider, "_session", None):
        await provider._session.close()
    await bridge.stop()
    await prisma_client.client.disconnect()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
