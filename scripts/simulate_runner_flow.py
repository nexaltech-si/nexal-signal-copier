"""
Simulated session for the runner option and the follow-up merge.

Real code under test: TradingService pipeline, RiskManager, SignalContinuity,
MT5RestProvider, ReplyHandlerService, DatabaseService (a real database).
Simulated: the broker (simulator/fake_mt5_bridge.py), Telegram (messages are
collected, not sent) and the AI (signals are built as the parser would return
them; reply commands and the follow-up classifier get fixed answers).

    DATABASE_URL=file:/path/sim.db python scripts/simulate_runner_flow.py [--serve]

Prints each step with the broker's and the database's state, then a PASS / FAIL
line per check. Exit code 1 when a check failed.

--serve keeps the simulated session alive for the dashboard: it leaves one setup
open (TP1 hit, TP2 order and runner running), starts the bot's API on
API_SERVER_PORT (default 8001) and keeps moving the price. Point the dashboard at
the same DATABASE_URL and SETTINGS_ENCRYPTION_KEY.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TELEGRAM_API_ID", "1")
os.environ.setdefault("TELEGRAM_API_HASH", "sim")
os.environ.setdefault("TELEGRAM_PHONE", "+10000000000")

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level=os.environ.get("SIM_LOG_LEVEL", "ERROR"))

import src.models  # noqa: E402,F401
from config import settings  # noqa: E402
from simulator.fake_mt5_bridge import FakeMT5Bridge  # noqa: E402
from src.models import TradingSignal, SignalAction, OrderType  # noqa: E402
from src.models.message import MessageIdentifier  # noqa: E402

CHANNEL, CHANNEL_NAME = "-1001234567890", "SIGNAL CHANNEL (simulated)"
checks = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok)))
    print(f"   {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(4, 74 - len(title)))


class FixedReplyAI:
    """Stands in for the reply LLM: the channel's words → the command it would return."""
    async def process_command(self, command, *a, **k):
        from ai.trade_command_processor import TradeCommand
        text = command.lower()
        if "close" in text:
            return TradeCommand(action="close_all", target="all")
        if "be" in text.split() or "breakeven" in text or "break even" in text:
            return TradeCommand(action="breakeven", target="all")
        return None


async def main() -> int:
    from src.core.prisma_client import prisma_client
    from src.core.database_service import db_service
    from src.integrations.telegram.unified_sender import notification_sender
    from src.integrations.trading.provider_manager import provider_manager
    from src.services.trading_service import trading_service
    from src.services.signal_continuity import signal_continuity
    from src.services.signal_service import signal_service
    from src.services.magic_number_service import magic_number_service
    from src.services.reply_handler_service import ReplyHandlerService
    from src.services.order_sync_service import order_sync_service
    from src.services.position_monitor_service import position_monitor_service

    # ── wiring ───────────────────────────────────────────────────────────────
    bridge = FakeMT5Bridge(bid=3945.0, balance=10000.0)
    url = await bridge.start(int(os.environ.get("SIM_BRIDGE_PORT", "5055")))
    for key, value in dict(
        trading_provider="mt5rest", mt5_rest_api_url=url, dry_run=False, skip_metaapi=False,
        max_risk_per_trade_percent=1.0, enable_trading_brain=False, enable_equity_protection=False,
        require_manual_approval=False, enable_signal_validator=False, copy_master_mode=False,
        enable_instant_execution=True, max_signal_age_minutes=5, runner_share_percent=50.0,
        enable_runner_split=False, min_lot_size=0.01,
        # position monitor: auto take profit on (it adds a TP to any position without one);
        # the profit-based rules off so every SL move below comes from a channel message
        enable_auto_take_profit=True, enable_auto_partial=False, enable_trailing_stop=False,
        enable_breakeven_move=False, enable_ai_market_analysis=False,
    ).items():
        setattr(settings, key, value)

    sent = []

    async def collect(message, *a, **k):
        sent.append(str(message))

    async def quiet(*a, **k):
        pass
    notification_sender.send_message = collect
    for name in dir(notification_sender):
        if name.startswith("notify_"):
            setattr(notification_sender, name, quiet)

    async def classify(raw_text, candidates):          # the follow-up classifier's answer
        waiting = [c for c in candidates if c["is_awaiting_levels"]]
        if waiting:
            return {"relationship": "FOLLOW_UP", "parent_id": waiting[0]["id"], "reason": "levels for the instant entry"}
        return {"relationship": "NEW", "parent_id": None, "reason": "a new setup"}
    signal_service.classify_signal_relationship = classify

    await prisma_client.initialize()
    await provider_manager.start()
    provider = provider_manager.proxy
    trading_service.set_trading_provider(provider)
    replies = ReplyHandlerService(trading_provider=provider, ai_processor=FixedReplyAI(), brain=None)

    def message(mid: int) -> MessageIdentifier:
        return MessageIdentifier(chat_id=CHANNEL, message_id=mid, message_hash=f"sim-{mid}",
                                 timestamp=datetime.now(timezone.utc))

    def signal(mid: int, raw: str, **kw) -> TradingSignal:
        base = dict(symbol="XAUUSD", action=SignalAction.OPEN, order_type=OrderType.SELL,
                    channel_id=CHANNEL, channel_name=CHANNEL_NAME, message_id=mid, raw_message=raw,
                    confidence=0.9, timestamp=datetime.now(timezone.utc))
        base.update(kw)
        s = TradingSignal(**base)
        s.telegram_message_id = message(mid)
        return s

    async def broker(magic: int):
        """Live orders of one setup as the bot reads them."""
        return sorted(await signal_continuity._live_orders({magic}, False), key=lambda o: o["id"])

    def show(orders) -> None:
        for o in orders:
            kind = "pending " if o["pending"] else "position"
            print(f"      {kind} #{o['id']}  {o['volume']:.2f} lots @ {o['openPrice']}  "
                  f"SL {o['stopLoss']}  TP {o['takeProfit'] or '— none (runner)'}")

    async def records(mid: int):
        sig = await db_service.db.signal.find_first(where={"channelId": CHANNEL, "messageId": mid},
                                                    include={"trades": True})
        return sig, (sig.trades if sig else [])

    async def sync() -> None:
        """What the bot's order sync does every few seconds: bring the trade records up to date.
        A close is only believed after it was seen missing on several passes in a row."""
        provider._positions_cache = provider._orders_cache = None
        for _ in range(order_sync_service.CLOSE_GRACE_MISSES + 1):
            await order_sync_service.sync_all_active_orders()

    async def tick(bid: float) -> None:
        events = bridge.tick(bid)
        print(f"   market → bid {bid}" + ("".join(f"\n      broker: {e}" for e in events) if events else ""))
        await sync()

    # ── 1. runner OFF: today's behaviour ─────────────────────────────────────
    step("1. Runner OFF — signal: SELL GOLD 3948, SL 3966, TP 3933 / 3910")
    await trading_service.process_signal(signal(
        101, "GOLD SELL @ 3948\nTP : 3933\nTP : 3910\nSL : 3966",
        entry_price=3948.0, stop_loss=3966.0, take_profit=[3933.0, 3910.0]))
    m1 = magic_number_service.generate_magic_number(101)
    live = await broker(m1)
    show(live)
    check("every order has a TP", live and all(o["takeProfit"] for o in live))
    await tick(3980.0)                       # a spike: both limits fill and stop out in one move
    sig, trades = await records(101)
    check("database: filled-and-stopped orders are closed with their loss, not cancelled",
          sig.status == "CLOSED" and all(t.status == "CLOSED" and (t.profitLoss or 0) < 0 for t in trades),
          f"signal {sig.status}, " + ", ".join(f"{t.status} {t.profitLoss}" for t in trades))
    await tick(3945.0)

    # ── 2. runner ON ─────────────────────────────────────────────────────────
    step("2. Runner ON (50%) — the same signal")
    settings.enable_runner_split = True
    sent.clear()
    await trading_service.process_signal(signal(
        102, "GOLD SELL @ 3948\nTP : 3933\nTP : 3910\nSL : 3966",
        entry_price=3948.0, stop_loss=3966.0, take_profit=[3933.0, 3910.0]))
    m2 = magic_number_service.generate_magic_number(102)
    live = await broker(m2)
    show(live)
    with_tp = [o for o in live if o["takeProfit"]]
    runners = [o for o in live if not o["takeProfit"]]
    total = round(sum(o["volume"] for o in live), 2)
    check("orders on the channel's TPs", sorted(o["takeProfit"] for o in with_tp) == [3910.0, 3933.0])
    check("one runner without TP, same SL", len(runners) == 1 and runners[0]["stopLoss"] == with_tp[0]["stopLoss"])
    check("runner is half of the lots", runners and abs(runners[0]["volume"] - total / 2) <= 0.011,
          f"{runners[0]['volume'] if runners else 0} of {total}")
    sig, trades = await records(102)
    check("one signal, all trades on it", sig is not None and len(trades) == len(live), f"{len(trades)} trades")
    runner_rows = [t for t in trades if t.takeProfit is None]
    check("runner trade: no TP, auto take profit off",
          len(runner_rows) == 1 and runner_rows[0].autoTpEnabled is False)
    check("owner told about the runner", any("runner" in s and "without TP" in s for s in sent))

    step("2a. Limit orders fill, price falls through TP1 and TP2")
    await tick(3948.5)
    await tick(3932.5)
    await tick(3909.5)
    live = await broker(m2)
    show(live)
    check("TP orders closed by the broker, runner still open",
          len(live) == 1 and not live[0]["pending"] and not live[0]["takeProfit"])
    for _ in range(3):                       # the position monitor's cycle (every few seconds live)
        provider._positions_cache = None
        await position_monitor_service._check_all_positions()
    provider._positions_cache = None
    live = await broker(m2)
    check("position monitor (auto take profit on) left the runner without TP",
          len(live) == 1 and not live[0]["takeProfit"])

    step("2b. Channel replies to the signal: \"Close now\"")
    result = await replies.handle_reply(reply_to_message_id=102, chat_id=CHANNEL, command="Close now",
                                        reply_message_id=1021, channel_name=CHANNEL_NAME)
    provider._positions_cache = None
    live = await broker(m2)
    print(f"   reply handler: {result.get('message') or result.get('error')}")
    check("runner closed by the channel's message", result.get("success") and not live)
    await sync()
    sig, trades = await records(102)
    check("database: all three trades closed with their profit, signal closed",
          sig.status == "CLOSED" and all(t.status == "CLOSED" and (t.profitLoss or 0) > 0 for t in trades),
          f"signal {sig.status}, " + ", ".join(f"{t.status} {t.profitLoss}" for t in trades))
    last = bridge.closed[-1]
    check("runner banked more than TP2 would have", last["price_close"] < 3910.0,
          f"closed at {last['price_close']}, {last['profit']:+.2f}")

    # ── 3. instant entry, then its follow-up ─────────────────────────────────
    step("3. \"GOLD SELL NOW\" (no levels), then the follow-up with levels")
    await tick(3947.5)
    sent.clear()
    await trading_service.process_signal(signal(
        201, "GOLD SELL NOW", entry_price=None, stop_loss=None, take_profit=[], instant_execution=True))
    m3 = magic_number_service.generate_magic_number(201)
    live = await broker(m3)
    show(live)
    check("instant entry: one position on a temporary SL, no runner",
          len(live) == 1 and live[0]["takeProfit"] and live[0]["stopLoss"])
    await asyncio.sleep(0.2)

    print("   follow-up: GOLD SELL NOW @ 3948 / TP 3933 / TP 3910 / SL 3966")
    await trading_service.process_signal(signal(
        202, "GOLD SELL NOW\n @ 3948\n\nTP : 3933\nTP : 3910\n\nSL : 3966",
        entry_price=3948.0, stop_loss=3966.0, take_profit=[3933.0, 3910.0], instant_execution=True))
    provider._positions_cache = provider._orders_cache = None
    live = await broker(m3)
    show(live)
    parent, parent_trades = await records(201)
    copy, _ = await records(202)
    check("follow-up created no second signal", copy is None)
    check("all orders are trades of the first signal", parent is not None and len(parent_trades) == len(live),
          f"{len(parent_trades)} trades, {len(live)} live orders")
    check("first signal shows the real levels", parent.stopLoss == 3966.0 and "3933" in (parent.takeProfit or ""))
    check("every order is on the real SL (pending ones spread-adjusted)",
          all(abs(o["stopLoss"] - 3966.0) <= 0.5 for o in live))
    runners = [o for o in live if not o["takeProfit"]]
    check("the added orders include a runner", len(runners) == 1)
    budget = bridge.balance * settings.max_risk_per_trade_percent / 100
    risk = sum((o["stopLoss"] - o["openPrice"]) * 100 * o["volume"] for o in live)
    check("whole setup stays within Max Risk Per Trade", risk <= budget * 1.05, f"{risk:.2f} of {budget:.2f}")

    step("3a. Channel edits the levels: SL 3970, TP 3930 / 3905")
    await signal_continuity.apply_update(parent, signal(
        202, "GOLD SELL NOW @ 3948 TP 3930 TP 3905 SL 3970",
        entry_price=3948.0, stop_loss=3970.0, take_profit=[3930.0, 3905.0]), message(202), source="edit")
    provider._positions_cache = provider._orders_cache = None
    live = await broker(m3)
    show(live)
    check("SL moved on every order, runner included (spread-adjusted)",
          all(abs(o["stopLoss"] - 3970.0) <= 0.5 for o in live))
    check("runner still has no TP", [o["id"] for o in live if not o["takeProfit"]] == [r["id"] for r in runners])

    step("3b. Limit orders fill, price falls, channel replies: \"BE\"")
    await tick(3948.0)
    await tick(3940.0)
    result = await replies.handle_reply(reply_to_message_id=202, chat_id=CHANNEL, command="BE",
                                        reply_message_id=2021, channel_name=CHANNEL_NAME)
    provider._positions_cache = provider._orders_cache = None
    live = await broker(m3)
    print(f"   reply handler: {result.get('message') or result.get('error')}")
    show(live)
    open_now = [o for o in live if not o["pending"]]
    check("open positions moved to break-even, runner included",
          result.get("success") and open_now and all(o["stopLoss"] <= o["openPrice"] for o in open_now))
    check("runner still has no TP", any(not o["takeProfit"] for o in live))

    step("3c. Price reverses to the break-even stops")
    await tick(3949.0)
    live = await broker(m3)
    show(live)
    check("runner closed at its break-even SL", not live and bridge.closed[-1]["reason"] == "SL")
    parent, parent_trades = await records(201)
    check("database: every trade of the setup is closed, signal closed",
          all(t.status == "CLOSED" for t in parent_trades) and parent.status == "CLOSED",
          f"signal {parent.status}, trades {[t.status for t in parent_trades]}")

    # ── 4. too small to split ────────────────────────────────────────────────
    step("4. Runner ON — a signal too small to split (wide SL → 0.01 lots)")
    await tick(3945.0)
    sent.clear()
    await trading_service.process_signal(signal(
        301, "GOLD SELL @ 3948 TP 3900 SL 4008", entry_price=3948.0, stop_loss=4008.0, take_profit=[3900.0]))
    live = await broker(magic_number_service.generate_magic_number(301))
    show(live)
    check("all lots stay on the TP, no runner", live and all(o["takeProfit"] for o in live))
    result = await replies.handle_reply(reply_to_message_id=301, chat_id=CHANNEL, command="Close now",
                                        reply_message_id=3011, channel_name=CHANNEL_NAME)
    provider._orders_cache = None
    print(f"   channel replies \"Close now\": {result.get('message') or result.get('error')}")
    check("unfilled order cancelled by the channel's message",
          not await broker(magic_number_service.generate_magic_number(301)))
    await sync()

    # ── result ───────────────────────────────────────────────────────────────
    step("Broker log (every order the bot sent)")
    for line in bridge.log:
        print(f"   {line}")
    unhandled = [line for line in bridge.log if line.startswith("??")]
    check("no request the simulated broker could not answer", not unhandled, "; ".join(unhandled))

    failed = [name for name, ok in checks if not ok]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks passed" +
          ("" if not failed else "\nFAILED:\n" + "\n".join(f"  • {n}" for n in failed)), flush=True)

    if "--serve" in sys.argv:
        step("Serving: one setup left open for the dashboard")
        await trading_service.process_signal(signal(
            401, "GOLD SELL @ 3948\nTP : 3933\nTP : 3910\nSL : 3966",
            entry_price=3948.0, stop_loss=3966.0, take_profit=[3933.0, 3910.0]))
        await tick(3948.5)
        await tick(3932.5)
        show(await broker(magic_number_service.generate_magic_number(401)))

        # the bot's API for the dashboard (settings / config page)
        import uvicorn
        from cryptography.fernet import Fernet
        from src.api.api_server import app, set_settings_service, set_settings_config
        from src.services.settings_service import get_settings_service
        generated = "SETTINGS_ENCRYPTION_KEY" not in os.environ
        key = os.environ.setdefault("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
        store = await get_settings_service(prisma_client.client, encryption_key=key)
        for name, value in {"TRADING_PROVIDER": "mt5rest", "MT5_REST_API_URL": url, "DRY_RUN": False,
                            "ENABLE_TRADING_BRAIN": False, "ENABLE_EQUITY_PROTECTION": False,
                            "ENABLE_AUTO_PARTIAL": False, "ENABLE_TRAILING_STOP": False,
                            "ENABLE_BREAKEVEN_MOVE": False, "ENABLE_RUNNER_SPLIT": True,
                            "RUNNER_SHARE_PERCENT": 50.0}.items():
            await store.set_setting(name, value, updated_by="simulation")
        settings.set_db_settings_service(store)
        set_settings_service(store)
        set_settings_config(settings)
        port = int(os.environ.get("API_SERVER_PORT", "8001"))
        class Server(uvicorn.Server):          # leave SIGTERM / Ctrl+C to this script
            def install_signal_handlers(self) -> None:
                pass
        server = Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        api = asyncio.create_task(server.serve())
        print(f"   bot API on http://127.0.0.1:{port}" +
              (f"  (generated SETTINGS_ENCRYPTION_KEY={key})" if generated else "") + "\n"
              f"   price now drifts between 3922 and 3931 — Ctrl+C to stop", flush=True)
        try:
            i = 0
            while not api.done():
                i += 1
                bridge.tick(3926.5 + 4.5 * (1 if i % 4 < 2 else -1) * ((i % 2) or 0.5))
                await sync()
                await asyncio.sleep(5)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        server.should_exit = True
    await provider_manager.stop()
    if getattr(provider, "_session", None):
        await provider._session.close()
    await bridge.stop()
    await prisma_client.client.disconnect()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
