"""
Full-flow simulated session: every message path of the bot except images.

    DATABASE_URL=file:/path/sim.db DEEPSEEK_API_KEY=... \\
        python scripts/simulate_full_flow.py [name-filter ...]

Each scenario gets its own channel, sends real-looking channel messages through
the bot's real message handler (see simulator/session.py for what is real and
what is simulated), prints what the bot said and what it sent to the broker,
and checks the outcome. `NOTE` lines are behaviour that works but that the
owner should decide on. A name filter runs only the scenarios containing it.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _key, _value in {      # before any import: the simulator package loads the bot's settings on import
    "TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "sim", "TELEGRAM_PHONE": "+10000000000",
    "PRIMARY_AI_PROVIDER": "deepseek", "FALLBACK_AI_PROVIDERS": "", "DEEPSEEK_MODEL": "deepseek-flash",
    "TRADING_PROVIDER": "mt5rest", "DRY_RUN": "false", "SKIP_METAAPI": "false",
    "MT5_REST_API_URL": f"http://127.0.0.1:{os.environ.get('SIM_BRIDGE_PORT', '5055')}",
}.items():
    os.environ.setdefault(_key, _value)
from simulator.session import Session, prepare_environment  # noqa: E402

prepare_environment()
import src.models  # noqa: E402,F401

SCENARIOS = []


def scenario(name: str):
    def register(fn):
        SCENARIOS.append((name, fn))
        return fn
    return register


# ── small helpers ────────────────────────────────────────────────────────────

def tps(orders) -> list:
    return sorted({o["takeProfit"] for o in orders if o["takeProfit"]})


def lots(orders) -> float:
    return round(sum(o["volume"] for o in orders), 2)


def risk(s: Session, orders) -> float:
    """Money lost if every order of the setup is stopped out."""
    total = 0.0
    for o in orders:
        if o["stopLoss"]:
            total += abs(o["openPrice"] - o["stopLoss"]) * s.bridge.spec(o["symbol"])["contract"] * o["volume"]
    return round(total, 2)


def budget(s: Session) -> float:
    return s.bridge.balance * s.settings_obj.max_risk_per_trade_percent / 100.0


def near(a, b, tol) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def all_sl(orders, level, tol=0.6) -> bool:
    return bool(orders) and all(near(o["stopLoss"], level, tol) for o in orders)


def within_budget(s: Session, orders) -> tuple:
    r, b = risk(s, orders), budget(s)
    return 0 < r <= b * 1.1, f"risk {r:.2f} of budget {b:.2f}"


# ═════════════════════════════════════════════════════════════════════════════
# 1. New signals: every shape a channel posts
# ═════════════════════════════════════════════════════════════════════════════

@scenario("signal: entry, SL and three TPs — full life to the last TP")
async def _(s: Session):
    ch = s.channel("Alpha")
    await s.tick(3945.0)
    m = await ch.post("XAUUSD SELL 3950\n\nSL 3962\nTP1 3940\nTP2 3930\nTP3 3915")
    o = await s.show(m)
    s.check("three pending SELL orders, one per TP", len(o) == 3 and all(x["pending"] for x in o)
            and tps(o) == [3915.0, 3930.0, 3940.0], f"TPs {tps(o)}")
    s.check("SL 3962 on every order", all_sl(o, 3962))
    s.check("sized within Max Risk Per Trade", *within_budget(s, o))
    await s.tick(3950.5)
    o = await s.show(m)
    s.check("orders fill when price reaches the entry", o and all(not x["pending"] for x in o))
    sig, trades = await s.record(ch, m)
    s.check("database: signal RUNNING, three trades RUNNING",
            sig.status == "RUNNING" and [t.status for t in trades] == ["RUNNING"] * 3,
            f"{sig.status} {[t.status for t in trades]}")
    await s.tick(3939.5)
    await s.tick(3929.5)
    await s.tick(3914.5)
    o = await s.show(m)
    sig, trades = await s.record(ch, m)
    s.check("all three TPs hit: nothing open, signal CLOSED, every trade closed in profit",
            not o and sig.status == "CLOSED" and all(t.status == "CLOSED" and (t.profitLoss or 0) > 0 for t in trades),
            f"{sig.status} " + ", ".join(f"{t.status} {t.profitLoss}" for t in trades))


@scenario("signal: stopped out — loss recorded")
async def _(s: Session):
    ch = s.channel("Alpha-SL")
    await s.tick(3945.0)
    m = await ch.post("GOLD BUY 3940\nSL 3930\nTP 3950\nTP 3960")
    await s.tick(3939.5)
    o = await s.show(m)
    s.check("BUY limits filled", o and all(not x["pending"] for x in o))
    await s.tick(3929.0)
    o = await s.show(m)
    sig, trades = await s.record(ch, m)
    total = round(sum(t.profitLoss or 0 for t in trades), 2)
    s.check("SL hit: nothing open, signal CLOSED, loss recorded and within the risk budget",
            not o and sig.status == "CLOSED" and -budget(s) * 1.15 <= total < 0, f"{sig.status}, P/L {total}")


@scenario("signal: entry zone (range)")
async def _(s: Session):
    ch = s.channel("Zone")
    await s.tick(3945.0)
    m = await ch.post("BUY GOLD 3940 - 3936\n\nSL 3930\nTP 3950\nTP 3960")
    o = await s.show(m)
    entries = sorted({o_["openPrice"] for o_ in o})
    s.check("orders placed inside the zone 3936–3940", o and all(3935.5 <= e <= 3940.6 for e in entries),
            f"entries {entries}")
    s.check("SL 3930 and TPs 3950 / 3960", all_sl(o, 3930) and tps(o) == [3950.0, 3960.0], f"TPs {tps(o)}")
    s.check("sized within Max Risk Per Trade", *within_budget(s, o))


@scenario("signal: two entries (scale-in)")
async def _(s: Session):
    ch = s.channel("Scale")
    await s.tick(3945.0)
    m = await ch.post("SELL GOLD @ 3950\nMORE SELL @ 3958\n\nSL 3966\nTP 3940\nTP 3925")
    o = await s.show(m)
    entries = sorted({round(x["openPrice"]) for x in o})
    s.check("orders at both entry levels", entries == [3950, 3958], f"entries {entries}")
    s.check("SL 3966 on all, TPs 3940 / 3925", all_sl(o, 3966) and tps(o) == [3925.0, 3940.0], f"TPs {tps(o)}")
    s.check("whole scale-in sized within Max Risk Per Trade", *within_budget(s, o))


@scenario("signal: buy stop (breakout entry above price)")
async def _(s: Session):
    ch = s.channel("Stop")
    await s.tick(3945.0)
    m = await ch.post("BUY STOP GOLD 3955\nSL 3945\nTP 3970")
    o = await s.show(m)
    s.check("pending BUY STOP above the market, not a market fill",
            o and all(x["pending"] and "STOP" in x["type"] for x in o), f"{[x['type'] for x in o]}")
    await s.tick(3955.5)
    o = await s.show(m)
    s.check("fills when price breaks up through 3955", o and all(not x["pending"] for x in o))
    await s.flatten()
    await s.tick(3945.0)
    m = await ch.post("SELL STOP XAUUSD 3938\nSL 3948\nTP 3928\nTP 3918")
    o = await s.show(m)
    s.check("SELL STOP with two TPs: two pending stop orders below the market",
            len(o) == 2 and all(x["pending"] and "STOP" in x["type"] for x in o) and tps(o) == [3918.0, 3928.0],
            f"{[x['type'] for x in o]}")
    await s.tick(3937.5)
    o = await s.show(m)
    s.check("both fill on the break below 3938", len(o) == 2 and all(not x["pending"] for x in o))


@scenario("signal: no take profit given")
async def _(s: Session):
    ch = s.channel("NoTP")
    await s.tick(3945.0)
    m = await ch.post("SELL GOLD 3950\nSL 3960")
    o = await s.show(m)
    s.check("trade placed with SL 3960", o and all_sl(o, 3960))
    s.check("a take profit was set automatically (none is never left open)", o and all(x["takeProfit"] for x in o),
            f"TPs {tps(o)}")


@scenario("signal: no stop loss given (not an instant entry)")
async def _(s: Session):
    ch = s.channel("NoSL")
    await s.tick(3945.0)
    mark = s.writes()
    m = await ch.post("SELL LIMIT GOLD 3950\nTP 3940\nTP 3930")
    o = await s.show(m)
    s.check("no order without a stop loss reaches the broker unprotected",
            all(x["stopLoss"] for x in o), f"{len(o)} orders")
    if o:
        s.finding(f"a limit signal without SL was traded with an SL the bot chose itself ({o[0]['stopLoss']})")
    else:
        s.finding("a limit signal without SL is not traded")


@scenario("signal: stop loss on the wrong side")
async def _(s: Session):
    ch = s.channel("BadSL")
    await s.tick(3945.0)
    mark = s.writes()
    m = await ch.post("BUY GOLD 3945\nSL 3955\nTP 3965")
    o = await s.show(m)
    s.check("nothing placed for a BUY with SL above the entry", not o and s.writes() == mark,
            "; ".join(s.since(mark)))


@scenario("signal: forex pair (EURUSD)")
async def _(s: Session):
    ch = s.channel("FX")
    await s.tick(1.08500, "EURUSD")
    m = await ch.post("EURUSD BUY 1.0840\nSL 1.0810\nTP 1.0880\nTP 1.0920")
    o = await s.show(m)
    s.check("EURUSD buy limits at 1.0840, SL 1.0810, TPs 1.0880 / 1.0920",
            o and all(x["symbol"] == "EURUSD" and near(x["openPrice"], 1.0840, 0.0003) for x in o)
            and all_sl(o, 1.0810, 0.0003) and tps(o) == [1.088, 1.092], f"TPs {tps(o)}")
    s.check("sized within Max Risk Per Trade", *within_budget(s, o))
    await s.tick(1.08390, "EURUSD")
    await s.tick(1.08810, "EURUSD")
    o = await s.show(m)
    s.check("TP1 closes one order, the other keeps running", len(o) == 1 and near(o[0]["takeProfit"], 1.092, 0.0001))


@scenario("signal: index and crypto (US30, BTCUSD)")
async def _(s: Session):
    ch = s.channel("Mixed")
    await s.tick(44200.0, "US30")
    await s.tick(98500.0, "BTCUSD")
    a = await ch.post("US30 BUY 44150\nSL 44000\nTP 44400")
    oa = await s.show(a)
    s.check("US30 order placed with its levels", oa and all(x["symbol"] == "US30" for x in oa)
            and all_sl(oa, 44000, 5) and tps(oa) == [44400.0])
    s.check("US30 sized within Max Risk Per Trade", *within_budget(s, oa))
    b = await ch.post("BTCUSD SELL 98800\nSL 99800\nTP 97500")
    ob = await s.show(b)
    s.check("BTCUSD order placed with its levels", ob and all(x["symbol"] == "BTCUSD" for x in ob)
            and all_sl(ob, 99800, 30) and tps(ob) == [97500.0])
    s.check("BTCUSD sized within Max Risk Per Trade", *within_budget(s, ob))


@scenario("signal: instrument written in words (Gold, Bitcoin, Euro)")
async def _(s: Session):
    ch = s.channel("Words")
    await s.tick(3945.0)
    await s.tick(98500.0, "BTCUSD")
    a = await ch.post("Sell Gold at 3950, stop 3961, targets 3940 and 3930")
    oa = await s.show(a)
    s.check("\"Gold\" in a sentence → XAUUSD order with SL 3961, TPs 3940 / 3930",
            oa and all(x["symbol"] == "XAUUSD" for x in oa) and all_sl(oa, 3961) and tps(oa) == [3930.0, 3940.0])
    b = await ch.post("Bitcoin long from 98200, stop loss 97200, take profit 99800")
    ob = await s.show(b)
    s.check("\"Bitcoin long\" → BTCUSD BUY with SL 97200, TP 99800",
            ob and all(x["symbol"] == "BTCUSD" and "BUY" in x["type"] for x in ob)
            and all_sl(ob, 97200, 30) and tps(ob) == [99800.0])


@scenario("signal: two trades in one message")
async def _(s: Session):
    ch = s.channel("Multi")
    await s.tick(3945.0)
    await s.tick(1.08500, "EURUSD")
    m = await ch.post("GOLD BUY 3940\nSL 3930\nTP 3955\n\nEURUSD SELL 1.0870\nSL 1.0900\nTP 1.0820")
    sigs = await s.signals(ch)
    symbols = sorted(x.symbol for x in sigs)
    placed = sorted({p["symbol"] for p in list(s.bridge.positions.values()) + list(s.bridge.orders.values())})
    s.check("both trades recognised as separate signals", symbols == ["EURUSD", "XAUUSD"], f"signals {symbols}")
    s.check("orders placed on both instruments", placed == ["EURUSD", "XAUUSD"], f"broker has {placed}")


@scenario("signal: non-English (Spanish)")
async def _(s: Session):
    ch = s.channel("ES")
    await s.tick(3945.0)
    m = await ch.post("ORO VENTA 3950\nStop: 3962\nObjetivo 1: 3940\nObjetivo 2: 3928")
    o = await s.show(m)
    s.check("Spanish signal → XAUUSD SELL, SL 3962, TPs 3940 / 3928",
            o and all(x["symbol"] == "XAUUSD" and "SELL" in x["type"] for x in o) and all_sl(o, 3962)
            and tps(o) == [3928.0, 3940.0], f"TPs {tps(o)}")


@scenario("signal: message that is too old")
async def _(s: Session):
    ch = s.channel("Old")
    await s.tick(3945.0)
    mark = s.writes()
    m = await ch.post("XAUUSD SELL 3950\nSL 3962\nTP 3940",
                      date=datetime.now(timezone.utc) - timedelta(minutes=45))
    s.check("a 45-minute-old signal is not traded", s.writes() == mark, "; ".join(s.since(mark)))


@scenario("signal: the same text posted twice")
async def _(s: Session):
    ch = s.channel("Twice")
    await s.tick(3945.0)
    text = "XAUUSD SELL 3950\nSL 3962\nTP 3940\nTP 3930"
    m = await ch.post(text)
    first = await s.orders(m)
    await ch.post(text)
    total = len(s.bridge.orders) + len(s.bridge.positions)
    sigs = await s.signals(ch)
    s.check("the repeat adds no orders", total == len(first), f"{len(first)} orders before, {total} after")
    s.check("still one signal", len(sigs) == 1, f"{len(sigs)} signals")


@scenario("signal: instrument the broker does not have")
async def _(s: Session):
    ch = s.channel("Unknown")
    mark = s.writes()
    m = await ch.post("NZDCHF BUY 0.5210\nSL 0.5180\nTP 0.5260")
    s.check("no order for an instrument the broker does not offer", s.writes() == mark, "; ".join(s.since(mark)))


@scenario("not a signal: commentary, promotion, analysis, results")
async def _(s: Session):
    ch = s.channel("Noise")
    await s.tick(3945.0)
    mark = s.writes()
    for text in [
        "Good morning traders ☀️ big news today at 15:30, stay ready and manage your risk",
        "Yesterday's result: +460 pips on GOLD 🔥 Join VIP for more signals",
        "Gold is looking bearish below 3950, I am waiting for a clean setup before any entry",
        "Weekly recap:\nGOLD SELL 3950 → TP3 ✅ +350 pips\nEURUSD BUY 1.0840 → SL ❌ -30 pips",
        "Don't sell gold now, wait for the retest of 3960 first",
        "If you missed the entry don't chase it, next signal coming soon",
    ]:
        await ch.post(text)
    s.check("no order for any of them", s.writes() == mark, "; ".join(s.since(mark)))
    s.check("no signal recorded", not await s.signals(ch), f"{len(await s.signals(ch))} signals")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Management sent as a REPLY to the signal
# ═════════════════════════════════════════════════════════════════════════════

async def running_sell(s: Session, ch, text="XAUUSD SELL 3950\n\nSL 3962\nTP1 3940\nTP2 3930\nTP3 3920",
                       start=3945.0, fill=3950.5) -> int:
    """A SELL setup whose limit orders have filled."""
    await s.tick(start)
    m = await ch.post(text)
    await s.tick(fill)
    return m


@scenario("reply: \"Close\" closes the whole setup")
async def _(s: Session):
    ch = s.channel("R-close")
    m = await running_sell(s, ch)
    await s.tick(3944.0)
    await ch.post("Close now ✅", reply_to=m)
    o = await s.show(m)
    sig, trades = await s.record(ch, m)
    s.check("nothing open, signal CLOSED, trades closed in profit",
            not o and sig.status == "CLOSED" and all(t.status == "CLOSED" and (t.profitLoss or 0) > 0 for t in trades),
            f"{sig.status} " + ", ".join(f"{t.status} {t.profitLoss}" for t in trades))


@scenario("reply: partial close (\"close half\", \"close 30%\")")
async def _(s: Session):
    ch = s.channel("R-partial")
    s.set(max_risk_per_trade_percent=3.0)        # lots large enough to halve
    m = await running_sell(s, ch)
    before = lots(await s.show(m))
    await s.tick(3944.0)
    await ch.post("Close half here and hold the rest", reply_to=m)
    o = await s.show(m)
    half = lots(o)
    s.check("about half of the lots closed, every order still running",
            len(o) == 3 and abs(half - before / 2) <= 0.03, f"{before} → {half} lots")
    await ch.post("Take 30% off", reply_to=m)
    o = await s.show(m)
    s.check("a further ~30% of the remaining lots closed", len(o) == 3 and abs(lots(o) - half * 0.7) <= 0.04,
            f"{half} → {lots(o)} lots")


@scenario("reply: stop-loss moves (break-even, to a price, lock profit)")
async def _(s: Session):
    ch = s.channel("R-sl")
    m = await running_sell(s, ch)
    await s.tick(3943.0)
    await ch.post("Move SL to 3955", reply_to=m)
    o = await s.show(m)
    s.check("\"Move SL to 3955\": SL 3955 on every position, TPs unchanged",
            all_sl(o, 3955) and tps(o) == [3920.0, 3930.0, 3940.0])
    await ch.post("Set breakeven", reply_to=m)
    o = await s.show(m)
    s.check("\"Set breakeven\": SL at the entry on every position", all_sl(o, 3950, 0.8))
    await s.tick(3941.0)
    await ch.post("Lock in 50 pips profit", reply_to=m)
    o = await s.show(m)
    s.check("\"Lock in 50 pips\": SL 5.0 beyond the entry, in profit", all_sl(o, 3945, 0.8),
            f"SLs {sorted({x['stopLoss'] for x in o})}")
    await s.tick(3945.5)
    o = await s.show(m)
    sig, trades = await s.record(ch, m)
    s.check("price returns: stopped out in profit at the locked SL",
            not o and all((t.profitLoss or 0) > 0 for t in trades), ", ".join(str(t.profitLoss) for t in trades))


@scenario("reply: take-profit change")
async def _(s: Session):
    ch = s.channel("R-tp")
    m = await running_sell(s, ch)
    await ch.post("Change TP to 3925", reply_to=m)
    o = await s.show(m)
    s.check("a TP at 3925 was applied, SL untouched", 3925.0 in tps(o) and all_sl(o, 3962), f"TPs {tps(o)}")
    if tps(o) == [3925.0]:
        s.finding("\"Change TP to 3925\" replaced all three TPs (3940 / 3930 / 3920) with 3925")


@scenario("reply: cancel before the entry is reached")
async def _(s: Session):
    ch = s.channel("R-cancel")
    await s.tick(3945.0)
    m = await ch.post("XAUUSD SELL LIMIT 3956\nSL 3966\nTP 3946\nTP 3936")
    o = await s.show(m)
    s.check("pending orders placed", o and all(x["pending"] for x in o))
    await ch.post("Cancel this one, setup is invalid", reply_to=m)
    o = await s.show(m)
    sig, trades = await s.record(ch, m)
    s.check("pending orders cancelled, signal CANCELLED",
            not o and sig.status == "CANCELLED" and all(t.status == "CANCELLED" for t in trades),
            f"{sig.status} {[t.status for t in trades]}")


@scenario("reply: scale-in — close one entry, hold the other")
async def _(s: Session):
    ch = s.channel("R-entry")
    await s.tick(3945.0)
    m = await ch.post("SELL GOLD @ 3950\nMORE SELL @ 3958\n\nSL 3968\nTP 3940\nTP 3925")
    await s.tick(3958.5)
    o = await s.show(m)
    s.check("both entries filled", o and all(not x["pending"] for x in o)
            and sorted({round(x["openPrice"]) for x in o}) == [3950, 3958])
    await s.tick(3952.0)
    await ch.post("Close the 3958 entry and hold 3950", reply_to=m)
    o = await s.show(m)
    left = sorted({round(x["openPrice"]) for x in o})
    s.check("only the 3958 entry closed, the 3950 entry still running", left == [3950], f"left open: {left}")


@scenario("reply: status updates and chatter change nothing")
async def _(s: Session):
    ch = s.channel("R-status")
    m = await running_sell(s, ch)
    await s.tick(3939.5)
    mark = s.writes()
    for text in ["TP1 hit ✅✅", "+100 pips running 🔥", "Who is in this trade? 🙋", "Hold tight, more to come",
                 "Great work team", "Still valid"]:
        await ch.post(text, reply_to=m)
    o = await s.show(m)
    s.check("no order touched by status / chatter replies", s.writes() == mark, "; ".join(s.since(mark)))
    s.check("TP2 and TP3 orders still running", tps(o) == [3920.0, 3930.0])


@scenario("reply: \"TP1 hit\" while the second entry never filled")
async def _(s: Session):
    ch = s.channel("R-tphit")
    await s.tick(3945.0)
    m = await ch.post("SELL GOLD @ 3950\nMORE SELL @ 3960\n\nSL 3970\nTP 3940\nTP 3925")
    await s.tick(3950.5)
    await s.tick(3939.5)
    o = await s.show(m)
    pend_before = [x for x in o if x["pending"]]
    await ch.post("TP1 hit ✅ +100 pips", reply_to=m)
    o = await s.show(m)
    pend_after = [x for x in o if x["pending"]]
    s.check("open positions untouched by the TP1 message", all(x["stopLoss"] for x in o if not x["pending"]))
    if pend_before and not pend_after:
        s.finding("after \"TP1 hit\" the unfilled second-entry orders (3960) were cancelled")
    elif pend_before:
        s.finding("after \"TP1 hit\" the unfilled second-entry orders (3960) stay pending")


@scenario("reply: re-entry on a setup that was stopped out")
async def _(s: Session):
    ch = s.channel("R-reentry")
    m = await running_sell(s, ch)
    await s.tick(3962.5)
    o = await s.show(m)
    s.check("first attempt stopped out", not o)
    await s.tick(3951.0)
    r = await ch.post("Re-enter SELL 3950 again\nSL 3963\nTP 3940\nTP 3928", reply_to=m)
    placed = [p for p in list(s.bridge.positions.values()) + list(s.bridge.orders.values())]
    s.check("the re-entry is placed as a new trade with its own levels",
            placed and all(near(p["sl"], 3963, 0.6) for p in placed), f"{len(placed)} orders, SL {[p['sl'] for p in placed]}")
    s.check("sized within Max Risk Per Trade",
            0 < sum(abs(p["price_open"] - p["sl"]) * 100 * p.get("volume", p.get("volume_current", 0)) for p in placed)
            <= budget(s) * 1.1)


@scenario("reply: to a message that is not a signal")
async def _(s: Session):
    ch = s.channel("R-nosignal")
    await s.tick(3945.0)
    chatter = await ch.post("Market is slow today, patience 🙏")
    m = await running_sell(s, ch)
    mark = s.writes()
    await ch.post("Close", reply_to=chatter)
    o = await s.show(m)
    if s.writes() == mark:
        s.finding("\"Close\" replying to a non-signal message did nothing; the running setup stays open")
    else:
        s.finding("\"Close\" replying to a non-signal message closed the channel's running setup: "
                  + "; ".join(s.since(mark)))
    s.check("no crash, state consistent", True)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Management sent as a plain post (NOT a reply)
# ═════════════════════════════════════════════════════════════════════════════

@scenario("plain post: close / break-even / SL move with one running setup")
async def _(s: Session):
    ch = s.channel("P-one")
    m = await running_sell(s, ch)
    await s.tick(3944.0)
    await ch.post("Move stop loss to breakeven")
    o = await s.show(m)
    s.check("\"Move stop loss to breakeven\" (no reply): SL at entry on the running setup", all_sl(o, 3950, 0.8))
    await ch.post("SL 3947 now")
    o = await s.show(m)
    s.check("\"SL 3947 now\" (no reply): SL 3947", all_sl(o, 3947, 0.8), f"SLs {sorted({x['stopLoss'] for x in o})}")
    await ch.post("Close all gold trades")
    o = await s.show(m)
    sig, _ = await s.record(ch, m)
    s.check("\"Close all gold trades\" (no reply): everything closed, signal CLOSED", not o and sig.status == "CLOSED",
            sig.status)


@scenario("plain post: status with one running setup changes nothing")
async def _(s: Session):
    ch = s.channel("P-status")
    m = await running_sell(s, ch)
    await s.tick(3939.5)
    mark = s.writes()
    for text in ["TP1 ✅", "100 pips 🔥🔥", "Running nicely", "Boom 💥"]:
        await ch.post(text)
    o = await s.show(m)
    s.check("no order touched", s.writes() == mark, "; ".join(s.since(mark)))
    s.check("TP2 and TP3 still running", tps(o) == [3920.0, 3930.0])


@scenario("plain post: two instruments running — the command names one")
async def _(s: Session):
    ch = s.channel("P-two-symbols")
    g = await running_sell(s, ch)
    await s.tick(1.08500, "EURUSD")
    e = await ch.post("EURUSD BUY 1.0840\nSL 1.0810\nTP 1.0880\nTP 1.0920")
    await s.tick(1.08390, "EURUSD")
    await s.tick(1.08600, "EURUSD")
    await s.tick(3944.0)
    await ch.post("Close EURUSD now")
    og, oe = await s.show(g), await s.show(e)
    s.check("\"Close EURUSD now\": EURUSD closed, gold untouched", not oe and len(og) == 3)
    await ch.post("Gold to breakeven")
    og = await s.show(g)
    s.check("\"Gold to breakeven\": gold SL at entry", all_sl(og, 3950, 0.8))


@scenario("plain post: two setups on the same instrument")
async def _(s: Session):
    ch = s.channel("P-two-setups")
    a = await running_sell(s, ch)
    await s.tick(3944.0)
    await ch.post("Set breakeven", reply_to=a)
    b = await ch.post("XAUUSD SELL 3944\nSL 3954\nTP 3934\nTP 3924")
    await s.tick(3944.5)
    oa, ob = await s.show(a), await s.show(b)
    s.check("second setup placed next to the first (first is at break-even)", len(oa) == 3 and len(ob) >= 1,
            f"{len(oa)} + {len(ob)} orders")
    await s.tick(3941.0)
    await ch.post("Close gold")
    oa, ob = await s.show(a), await s.show(b)
    if not oa and not ob:
        s.finding("plain \"Close gold\" with two gold setups running closed BOTH setups")
    elif not ob and oa:
        s.finding("plain \"Close gold\" with two gold setups running closed only the LATEST setup")
    elif not oa and ob:
        s.finding("plain \"Close gold\" with two gold setups running closed only the OLDER setup")
    else:
        s.finding("plain \"Close gold\" with two gold setups running closed nothing")
    s.check("at least the latest setup reacted to the close", not ob)


@scenario("plain post: command with nothing running")
async def _(s: Session):
    ch = s.channel("P-nothing")
    await s.tick(3945.0)
    mark = s.writes()
    for text in ["Close all trades", "Move SL to breakeven", "B.E", "TP1 hit ✅"]:
        await ch.post(text)
    s.check("nothing sent to the broker, no crash", s.writes() == mark, "; ".join(s.since(mark)))
    s.check("no signal recorded", not await s.signals(ch))


@scenario("plain post: another channel's command must not touch this channel's trade")
async def _(s: Session):
    a, b = s.channel("Chan-A"), s.channel("Chan-B")
    m = await running_sell(s, a)
    await s.tick(3944.0)
    mark = s.writes()
    for text in ["Close gold now", "Move SL to breakeven", "B.E"]:
        await b.post(text)
    o = await s.show(m)
    s.check("channel A's setup untouched by channel B's commands", s.writes() == mark and len(o) == 3
            and all_sl(o, 3962), "; ".join(s.since(mark)))


@scenario("two channels post the identical signal seconds apart")
async def _(s: Session):
    a, b = s.channel("VIP"), s.channel("Mirror")
    await s.tick(3945.0)
    text = "XAUUSD SELL 3950\n\nSL 3962\nTP1 3940\nTP2 3930"
    ma = await a.post(text)
    mb = await b.post(text)
    sa, ta = await s.record(a, ma)
    sb, tb = await s.record(b, mb)
    s.check("each channel has its own signal with its own trades",
            sa is not None and sb is not None and sa.id != sb.id and len(ta) == 2 and len(tb) == 2,
            f"A: {len(ta)} trades, B: {'no signal' if sb is None else str(len(tb)) + ' trades'}")
    await s.tick(3950.5)
    await s.tick(3945.0)
    await b.post("Gold to breakeven")
    oa, ob = await s.show(ma), await s.show(mb)
    s.check("the mirror channel's plain command manages the mirror channel's trade only",
            all_sl(ob, 3950, 0.8) and all_sl(oa, 3962))


# ═════════════════════════════════════════════════════════════════════════════
# 4. Edits, deletes, reposts
# ═════════════════════════════════════════════════════════════════════════════

@scenario("edit: SL and TPs of a running setup")
async def _(s: Session):
    ch = s.channel("E-run")
    m = await running_sell(s, ch)
    await ch.edit(m, "XAUUSD SELL 3950\n\nSL 3958\nTP1 3942\nTP2 3932\nTP3 3922")
    o = await s.show(m)
    s.check("edited SL 3958 and TPs 3942 / 3932 / 3922 applied to the running positions",
            all_sl(o, 3958) and tps(o) == [3922.0, 3932.0, 3942.0], f"TPs {tps(o)}")
    s.check("no second signal, no new orders", len(await s.signals(ch)) == 1 and len(o) == 3)


@scenario("edit: entry level of a setup that has not filled")
async def _(s: Session):
    ch = s.channel("E-entry")
    await s.tick(3945.0)
    m = await ch.post("XAUUSD SELL LIMIT 3956\nSL 3966\nTP 3946\nTP 3936")
    o = await s.show(m)
    s.check("pending at 3956", o and all(near(x["openPrice"], 3956, 0.6) for x in o))
    await ch.edit(m, "XAUUSD SELL LIMIT 3960\nSL 3970\nTP 3950\nTP 3940")
    o = await s.show(m)
    entries = sorted({round(x["openPrice"]) for x in o})
    s.check("no order left at the old level 3956", 3956 not in entries, f"entries {entries}")
    s.check("orders now at 3960 with SL 3970 and TPs 3950 / 3940",
            entries == [3960] and all_sl(o, 3970) and tps(o) == [3940.0, 3950.0], f"entries {entries} TPs {tps(o)}")
    s.check("still within Max Risk Per Trade", *within_budget(s, o))


@scenario("edit: cosmetic change (emoji, typo) does nothing")
async def _(s: Session):
    ch = s.channel("E-cosmetic")
    m = await running_sell(s, ch)
    mark = s.writes()
    await ch.edit(m, "🔥 XAUUSD SELL 3950 🔥\n\nSL 3962\nTP1 3940\nTP2 3930\nTP3 3920\n\nGood luck!")
    s.check("no order touched", s.writes() == mark, "; ".join(s.since(mark)))


@scenario("edit: a chatter message is edited into a signal")
async def _(s: Session):
    ch = s.channel("E-late")
    await s.tick(3945.0)
    m = await ch.post("Signal coming in a minute, get ready 👀")
    await ch.edit(m, "XAUUSD SELL 3950\n\nSL 3962\nTP1 3940\nTP2 3930")
    o = await s.show(m)
    if o:
        s.check("the edited-in signal is placed with its levels", all_sl(o, 3962) and tps(o) == [3930.0, 3940.0])
    else:
        s.finding("a message first posted as chatter and then edited into a full signal is NOT traded")
        s.check("no crash", True)


@scenario("edit: the signal text is replaced by a cancellation")
async def _(s: Session):
    ch = s.channel("E-void")
    await s.tick(3945.0)
    m = await ch.post("XAUUSD SELL LIMIT 3956\nSL 3966\nTP 3946\nTP 3936")
    await ch.edit(m, "❌ CANCELLED — setup no longer valid, do not enter")
    o = await s.show(m)
    if not o:
        s.finding("editing a pending signal into \"CANCELLED\" cancels its pending orders")
    else:
        s.finding("editing a pending signal into \"CANCELLED — do not enter\" leaves its pending orders in place")
    s.check("no crash", True)


@scenario("delete: a running setup, then a repost with new levels")
async def _(s: Session):
    ch = s.channel("D-repost")
    m = await running_sell(s, ch)
    await ch.delete(m)
    o = await s.show(m)
    s.check("delete keeps the open positions with their SL / TP", len(o) == 3 and all_sl(o, 3962))
    r = await ch.post("XAUUSD SELL 3950\n\nSL 3960\nTP1 3941\nTP2 3931\nTP3 3921")
    o = await s.show(m)
    s.check("repost updates the same positions: SL 3960, TPs 3941 / 3931 / 3921",
            len(o) == 3 and all_sl(o, 3960) and tps(o) == [3921.0, 3931.0, 3941.0], f"TPs {tps(o)}")
    s.check("no second signal, no extra orders", len(await s.signals(ch)) == 1
            and len(s.bridge.positions) + len(s.bridge.orders) == 3)
    await ch.post("Close now", reply_to=r)
    o = await s.show(m)
    s.check("a reply to the REPOST manages the original setup", not o)


@scenario("delete: a message that is not a signal")
async def _(s: Session):
    ch = s.channel("D-chatter")
    m = await running_sell(s, ch)
    c = await ch.post("Good trade so far 👍")
    mark = s.writes()
    await ch.delete(c)
    s.check("nothing happens", s.writes() == mark and len(await s.orders(m)) == 3)


# ═════════════════════════════════════════════════════════════════════════════
# 5. Risk rules, limits and protections
# ═════════════════════════════════════════════════════════════════════════════

@scenario("risk: lot size follows the stop distance and the risk setting")
async def _(s: Session):
    ch = s.channel("K-size")
    await s.tick(3945.0)
    tight = await ch.post("XAUUSD SELL LIMIT 3950\nSL 3955\nTP 3940")
    ot = await s.show(tight)
    s.check("tight SL (5.0): risk within the 1% budget", *within_budget(s, ot))
    await s.flatten()
    wide = await ch.post("XAUUSD SELL LIMIT 3951\nSL 3981\nTP 3921")
    ow = await s.show(wide)
    s.check("wide SL (30.0): risk within the 1% budget", *within_budget(s, ow))
    s.check("wider stop → smaller position", ot and ow and lots(ow) < lots(ot), f"{lots(ot)} vs {lots(ow)} lots")
    await s.flatten()
    s.set(max_risk_per_trade_percent=0.5)
    half = await ch.post("XAUUSD SELL LIMIT 3952\nSL 3957\nTP 3942")
    oh = await s.show(half)
    s.check("risk setting halved → risk within the 0.5% budget", *within_budget(s, oh))


@scenario("risk: stop so wide that even the minimum lot is over budget")
async def _(s: Session):
    ch = s.channel("K-toowide")
    s.set(max_risk_per_trade_percent=0.2)
    await s.tick(3945.0)
    mark = s.writes()
    m = await ch.post("XAUUSD SELL LIMIT 3950\nSL 4010\nTP 3900")
    o = await s.show(m)
    if not o:
        s.check("not traded: 0.01 lots would risk more than the budget", s.writes() == mark)
    else:
        r = risk(s, o)
        s.finding(f"a signal whose minimum lot risks {r:.2f} was traded although the budget is {budget(s):.2f}")
        s.check("traded at the minimum lot only", lots(o) == 0.01, f"{lots(o)} lots")


@scenario("risk: maximum number of open setups")
async def _(s: Session):
    ch = s.channel("K-max")
    s.set(max_open_positions=2)
    await s.tick(3945.0)
    await s.tick(1.08500, "EURUSD")
    await s.tick(98500.0, "BTCUSD")
    a = await ch.post("XAUUSD SELL 3944\nSL 3956\nTP 3934")
    b = await ch.post("EURUSD SELL 1.0849\nSL 1.0879\nTP 1.0809")
    oa, ob = await s.orders(a), await s.orders(b)
    s.check("first two setups are open positions", oa and ob and all(not x["pending"] for x in oa + ob))
    mark = s.writes()
    c = await ch.post("BTCUSD SELL 98490\nSL 99490\nTP 97000")
    oc = await s.show(c)
    s.check("third setup refused: Max Open Positions is 2", not oc and s.writes() == mark, "; ".join(s.since(mark)))


@scenario("risk: second signal at the same level while the first is at risk")
async def _(s: Session):
    ch = s.channel("K-level")
    m = await running_sell(s, ch)
    before = len(s.bridge.positions) + len(s.bridge.orders)
    n = await ch.post("GOLD SELL 3950 again!\n\nSL 3963\nTP 3938\nTP 3926")
    after = len(s.bridge.positions) + len(s.bridge.orders)
    sigs = await s.signals(ch)
    if after == before:
        s.finding(f"a second SELL at the same level (first not at break-even) added no orders; signals recorded: {len(sigs)}")
    else:
        s.finding(f"a second SELL at the same level (first not at break-even) added {after - before} order(s)")
    total = list(s.bridge.positions.values()) + list(s.bridge.orders.values())
    exposure = sum(abs(p["price_open"] - p["sl"]) * 100 * p.get("volume", p.get("volume_current", 0)) for p in total)
    s.check("total gold risk of the channel stays within two budgets", exposure <= 2 * budget(s) * 1.1,
            f"{exposure:.2f} at risk, one budget is {budget(s):.2f}")


@scenario("risk: opposite signal while a setup is running")
async def _(s: Session):
    ch = s.channel("K-opposite")
    m = await running_sell(s, ch)
    await s.tick(3946.0)
    n = await ch.post("XAUUSD BUY 3946\nSL 3936\nTP 3956\nTP 3966")
    osell, obuy = await s.show(m), await s.show(n)
    if obuy and osell:
        s.finding("a BUY signal while the channel's SELL is running opens the BUY next to it (hedged); the SELL is not closed")
    elif obuy and not osell:
        s.finding("a BUY signal while the channel's SELL is running closed the SELL and opened the BUY")
    else:
        s.finding("a BUY signal while the channel's SELL is running was not traded")
    s.check("no crash, both setups consistent", True)


@scenario("risk: total risk cap per instrument")
async def _(s: Session):
    ch1, ch2 = s.channel("K-cap-1"), s.channel("K-cap-2")
    s.set(max_total_risk_per_symbol_percent=1.5)
    await s.tick(3945.0)
    a = await ch1.post("XAUUSD SELL 3944\nSL 3956\nTP 3934\nTP 3924")
    b = await ch2.post("XAUUSD SELL 3943\nSL 3957\nTP 3931\nTP 3921")
    oa, ob = await s.show(a), await s.show(b)
    ra_, rb_ = risk(s, oa), risk(s, ob)
    cap = s.bridge.balance * 0.015
    s.check("two channels on gold: combined risk stays within the 1.5% cap", 0 < ra_ + rb_ <= cap * 1.1,
            f"{ra_:.2f} + {rb_:.2f} = {ra_ + rb_:.2f}, cap {cap:.2f}")
    s.check("the second setup was sized down, not skipped", ob and rb_ < ra_, f"second risks {rb_:.2f}")


@scenario("protection: manual approval — approve, reject")
async def _(s: Session):
    from src.services.approval_queue import approval_queue
    ch = s.channel("K-approval")
    s.set(require_manual_approval=True)
    await s.tick(3945.0)
    mark = s.writes()
    m = await ch.post("XAUUSD SELL 3950\n\nSL 3962\nTP1 3940\nTP2 3930")
    sig, _ = await s.record(ch, m)
    pending = approval_queue.get_all_pending()
    s.check("signal waits for approval: nothing at the broker, status AWAITING_APPROVAL",
            s.writes() == mark and sig and sig.status == "AWAITING_APPROVAL" and len(pending) == 1,
            f"{sig.status if sig else None}, {len(pending)} in queue")
    item = pending[0]
    approval_queue.approve_signal(item.signal_id)
    await s.db.update_signal_status(item.signal_id, "PROCESSING")
    await s.deliver("owner approves", s.trading_service.execute_after_approval(
        item.signal, item.risk_assessment, item.signal_id))
    o = await s.show(m)
    s.check("after approval the orders are placed", len(o) == 2 and all_sl(o, 3962))
    await s.flatten()

    mark = s.writes()
    n = await ch.post("XAUUSD BUY 3940\n\nSL 3930\nTP1 3950\nTP2 3960")
    item = approval_queue.get_all_pending()[0]
    approval_queue.reject_signal(item.signal_id, "Rejected by owner")
    await s.deliver("owner rejects", asyncio.sleep(0.2))
    sig, _ = await s.record(ch, n)
    s.check("after rejection nothing is placed, signal REJECTED", s.writes() == mark and sig.status == "REJECTED",
            sig.status)


@scenario("protection: news block")
async def _(s: Session):
    import importlib
    news_module = importlib.import_module("src.services.news_service")
    ts_module = sys.modules["src.services.trading_service"]
    from src.services.news_trading_service import NewsTradingService
    ch = s.channel("K-news")
    nts = NewsTradingService(notification_service=None)
    nts.enable_news_filter = True
    now = datetime.now(nts.server_tz)
    nts.active_news_blocks["XAUUSD"] = {"start_time": now - timedelta(minutes=5), "end_time": now + timedelta(minutes=25),
                                        "reason": "US CPI (high impact) at 15:30"}
    previous = (news_module.news_trading_service, ts_module.news_trading_service)
    news_module.news_trading_service = ts_module.news_trading_service = nts
    try:
        await s.tick(3945.0)
        await s.tick(1.08500, "EURUSD")
        mark = s.writes()
        m = await ch.post("XAUUSD SELL 3950\n\nSL 3962\nTP1 3940")
        sig, _ = await s.record(ch, m)
        s.check("gold signal during the news window is not traded and is recorded as rejected",
                s.writes() == mark and sig is not None and sig.status == "REJECTED",
                f"{sig.status if sig else 'no record'}; " + "; ".join(s.since(mark)))
        e = await ch.post("EURUSD SELL 1.0860\nSL 1.0890\nTP 1.0820")
        s.check("an instrument without a news block is still traded", bool(await s.show(e)))
    finally:
        news_module.news_trading_service, ts_module.news_trading_service = previous


@scenario("protection: daily drawdown limit")
async def _(s: Session):
    from src.services.drawdown_monitor_service import drawdown_monitor_service as monitor
    from src.services.drawdown_protection_service import drawdown_protection_service as protection
    ch = s.channel("K-drawdown")
    s.set(enable_equity_protection=True, daily_drawdown_limit_percent=3.0, max_risk_per_trade_percent=5.0)
    await s.tick(3945.0)
    protection.reset_state()
    monitor._monitor_interval_seconds = monitor._live_interval_seconds = 1
    await monitor.start_monitoring()
    try:
        m = await ch.post("XAUUSD SELL 3944\nSL 3964\nTP 3924")
        p = await ch.post("XAUUSD SELL LIMIT 3970\nSL 3990\nTP 3950")
        o = await s.show(m)
        s.check("a 5%-risk position is open, plus a pending setup", o and not o[0]["pending"] and await s.orders(p))
        s.bridge.tick(3961.0)                      # floating loss above 3% of the balance
        s.out("   market: XAUUSD bid 3961.0 (floating loss above the 3% daily limit, SL not reached)")
        for _ in range(12):
            await asyncio.sleep(1)
            if protection.is_trading_paused:
                break
        await s.sync()
        s.report()
        s.check("breach detected: trading paused", protection.is_trading_paused)
        s.check("losing position closed and pending orders cancelled by the protection",
                not s.bridge.positions and not s.bridge.orders,
                f"{len(s.bridge.positions)} positions, {len(s.bridge.orders)} pending")
        mark = s.writes()
        n = await ch.post("XAUUSD SELL 3960\nSL 3970\nTP 3950")
        s.check("new signals are refused while trading is paused", s.writes() == mark, "; ".join(s.since(mark)))
    finally:
        await monitor.stop_monitoring()
        protection.reset_state()


# ═════════════════════════════════════════════════════════════════════════════
# 6. Automation: what the bot does on its own while a trade runs
# ═════════════════════════════════════════════════════════════════════════════

@scenario("automation: break-even after a profit in pips")
async def _(s: Session):
    ch = s.channel("A-be-pips")
    s.set(enable_breakeven_move=True, breakeven_trigger_method="PROFIT_PIPS", breakeven_trigger_pips=30,
          breakeven_buffer_pips=2)
    m = await running_sell(s, ch, "XAUUSD SELL 3950\n\nSL 3962\nTP 3920")
    await s.tick(3948.5)
    o = await s.show(m)
    s.check("12 pips in profit: SL not moved yet", all_sl(o, 3962))
    await s.tick(3946.0)
    o = await s.show(m)
    s.check("over 30 pips in profit: SL moved to the entry (with its buffer), TP unchanged",
            o and all(3948.5 <= x["stopLoss"] <= 3950.0 for x in o) and tps(o) == [3920.0],
            f"SL {[x['stopLoss'] for x in o]}")


@scenario("automation: break-even after the first TP of the setup is hit")
async def _(s: Session):
    ch = s.channel("A-be-tp")
    s.set(enable_breakeven_move=True, breakeven_trigger_method="AFTER_SIBLING_TP_HIT", breakeven_min_sibling_tp_hits=1)
    m = await running_sell(s, ch)
    await s.tick(3944.0)
    o = await s.show(m)
    s.check("before TP1: SL still 3962", all_sl(o, 3962))
    await s.tick(3939.5)
    await s.sync()
    s.report()
    o = await s.show(m)
    s.check("TP1 hit: the two remaining positions are at break-even",
            len(o) == 2 and all(x["stopLoss"] <= x["openPrice"] + 0.01 for x in o), f"SL {[x['stopLoss'] for x in o]}")


@scenario("automation: automatic partial close, then break-even")
async def _(s: Session):
    ch = s.channel("A-partial")
    s.set(max_risk_per_trade_percent=3.0, enable_auto_partial=True, auto_partial_calculation_method="RR",
          auto_partial_trigger_rr=1.0, auto_partial_close_percent=50.0,
          enable_breakeven_move=True, breakeven_trigger_method="AFTER_PARTIAL")
    m = await running_sell(s, ch, "XAUUSD SELL 3950\n\nSL 3962\nTP 3915")
    before = lots(await s.show(m))
    await s.tick(3945.0)
    s.check("below 1R profit: nothing closed", lots(await s.orders(m)) == before)
    await s.tick(3936.5)
    await s.sync()
    s.report()
    o = await s.show(m)
    s.check("at 1R profit: half of the position closed", o and abs(lots(o) - before / 2) <= 0.02,
            f"{before} → {lots(o)} lots")
    s.check("and the rest moved to break-even", o and all(x["stopLoss"] <= x["openPrice"] + 0.01 for x in o),
            f"SL {[x['stopLoss'] for x in o]}")


@scenario("automation: trailing stop")
async def _(s: Session):
    ch = s.channel("A-trail")
    s.set(enable_trailing_stop=True, trailing_stop_calculation_method="PIPS", trailing_stop_distance_pips=30,
          trailing_activation_method="PROFIT_PIPS", trailing_activation_profit_pips=40,
          trailing_stop_min_interval_seconds=0)
    m = await running_sell(s, ch, "XAUUSD SELL 3950\n\nSL 3962\nTP 3900")
    await s.tick(3948.0)
    s.check("20 pips in profit: SL not trailing yet", all_sl(await s.orders(m), 3962))
    await s.tick(3944.0)
    await s.tick(3938.0)
    await s.sync()
    s.report()
    o = await s.show(m)
    first = o[0]["stopLoss"] if o else None
    s.check("after 40+ pips the SL trails about 30 pips behind price (near 3941)",
            o and 3940.0 <= first <= 3942.5, f"SL {first}")
    await s.tick(3930.0)
    await s.sync()
    s.report()
    o = await s.show(m)
    second = o[0]["stopLoss"] if o else None
    s.check("price falls further: SL follows down (near 3933)", o and second < first and 3932.0 <= second <= 3934.5,
            f"SL {second}")
    await s.tick(3934.5)
    o = await s.show(m)
    sig, trades = await s.record(ch, m)
    s.check("price turns: stopped out in profit at the trailed SL",
            not o and all((t.profitLoss or 0) > 0 for t in trades), ", ".join(str(t.profitLoss) for t in trades))


# ═════════════════════════════════════════════════════════════════════════════
# 7. Things that happen outside Telegram: the terminal, restarts
# ═════════════════════════════════════════════════════════════════════════════

@scenario("terminal: owner closes a position and cancels an order by hand")
async def _(s: Session):
    ch = s.channel("T-manual")
    m = await running_sell(s, ch)
    o = await s.orders(m)
    await s.tick(3945.0)
    s.bridge.manual_close(int(o[0]["id"]))
    s.out(f"   owner closes position #{o[0]['id']} in the MT5 terminal")
    await s.sync()
    s.report()
    sig, trades = await s.record(ch, m)
    states = sorted(t.status for t in trades)
    s.check("database follows: one trade CLOSED with its profit, two RUNNING, signal PARTIALLY_CLOSED",
            states == ["CLOSED", "RUNNING", "RUNNING"] and sig.status == "PARTIALLY_CLOSED"
            and any(t.status == "CLOSED" and (t.profitLoss or 0) > 0 for t in trades), f"{sig.status} {states}")
    await ch.post("Close all", reply_to=m)
    sig, trades = await s.record(ch, m)
    s.check("the channel's close still closes the other two; signal CLOSED",
            not await s.orders(m) and sig.status == "CLOSED" and all(t.status == "CLOSED" for t in trades), sig.status)

    await s.tick(3945.0)
    p = await ch.post("XAUUSD SELL LIMIT 3957\nSL 3967\nTP 3947")
    o = await s.orders(p)
    s.bridge.manual_cancel(int(o[0]["id"]))
    s.out(f"   owner cancels pending order #{o[0]['id']} in the MT5 terminal")
    await s.sync()
    s.report()
    sig, trades = await s.record(ch, p)
    s.check("database follows: trade CANCELLED, signal CANCELLED",
            sig.status == "CANCELLED" and all(t.status == "CANCELLED" for t in trades),
            f"{sig.status} {[t.status for t in trades]}")


@scenario("terminal: owner moves the SL by hand, then the channel says break-even")
async def _(s: Session):
    ch = s.channel("T-sl")
    m = await running_sell(s, ch)
    for p in s.bridge.positions.values():
        p["sl"] = 3958.0
    s.out("   owner sets SL 3958 on all three positions in the MT5 terminal")
    await s.sync()
    s.report()
    _, trades = await s.record(ch, m)
    s.check("database shows the hand-set SL", all(near(t.stopLoss, 3958, 0.1) for t in trades),
            f"{[t.stopLoss for t in trades]}")
    await s.tick(3944.0)
    await ch.post("Breakeven now", reply_to=m)
    s.check("the channel's break-even still applies on top", all_sl(await s.show(m), 3950, 0.8))


@scenario("terminal: a position the bot did not open is left alone")
async def _(s: Session):
    ch = s.channel("T-foreign")
    await s.tick(3945.0)
    t = s.bridge._next()
    s.bridge.positions[t] = dict(ticket=t, symbol="XAUUSD", type=1, volume=0.10, price_open=3945.0, sl=0.0, tp=0.0,
                                 magic=0, comment="manual", time=__import__("time").time())
    s.out(f"   owner opens SELL 0.10 gold by hand in the MT5 terminal (#{t}, no SL, no TP)")
    m = await running_sell(s, ch)
    await s.tick(3944.0)
    await ch.post("Close all gold trades")
    mine = s.bridge.positions.get(t)
    s.check("the channel's \"close all gold\" closed the bot's setup only; the manual position is still open",
            not await s.orders(m) and mine is not None)
    s.check("the bot did not add an SL or TP to the manual position",
            mine is not None and mine["sl"] == 0.0 and mine["tp"] == 0.0, f"{mine}")


@scenario("restart: the same message delivered again is not traded twice")
async def _(s: Session):
    ch = s.channel("X-replay")
    m = await running_sell(s, ch)
    before = len(s.bridge.positions) + len(s.bridge.orders)
    await s.restart()
    await ch.redeliver(m)
    after = len(s.bridge.positions) + len(s.bridge.orders)
    s.check("no second set of orders", after == before, f"{before} → {after}")
    s.check("still one signal", len(await s.signals(ch)) == 1)


@scenario("restart: between \"SELL NOW\" and its levels")
async def _(s: Session):
    ch = s.channel("X-instant")
    await s.tick(3947.5)
    first = await ch.post("GOLD SELL NOW")
    o = await s.show(first)
    s.check("instant entry open on a temporary SL", len(o) == 1 and not o[0]["pending"] and o[0]["stopLoss"])
    await s.restart()
    await ch.post("GOLD SELL NOW\n @ 3948\n\nTP : 3933\nTP : 3910\n\nSL : 3966")
    o = await s.show(first)
    s.check("after the restart the levels still update the first signal: one signal, SL 3966",
            len(await s.signals(ch)) == 1 and all_sl(o, 3966), f"{len(await s.signals(ch))} signals")


@scenario("restart: a command for a trade opened before the restart")
async def _(s: Session):
    ch = s.channel("X-command")
    m = await running_sell(s, ch)
    await s.tick(3944.0)
    await s.restart()
    await ch.post("Move SL to breakeven")
    s.check("plain command after the restart still finds and manages the running setup",
            all_sl(await s.show(m), 3950, 0.8))
    await ch.post("Close", reply_to=m)
    s.check("reply after the restart closes it", not await s.orders(m))


# ═════════════════════════════════════════════════════════════════════════════
# 8. Instant entries, follow-ups, the runner option
# ═════════════════════════════════════════════════════════════════════════════

@scenario("instant: \"SELL NOW\", levels follow, chatter, TP, close")
async def _(s: Session):
    ch = s.channel("I-flow")
    await s.tick(3947.5)
    first = await ch.post("GOLD SELL NOW")
    o = await s.show(first)
    s.check("one position at market on a temporary SL", len(o) == 1 and not o[0]["pending"] and o[0]["stopLoss"])
    follow = await ch.post("GOLD SELL NOW\n @ 3948\n\nTP : 3933\nTP : 3910\n\nSL : 3966")
    o = await s.show(first)
    sig, trades = await s.record(ch, first)
    s.check("levels applied to the same signal: one signal, SL 3966 on everything",
            len(await s.signals(ch)) == 1 and all_sl(o, 3966) and len(trades) == len(o))
    s.check("whole setup within Max Risk Per Trade", *within_budget(s, o))
    mark = s.writes()
    for text in ["Enter now", "Running!", "On its way"]:
        await ch.post(text, reply_to=follow)
    s.check("chatter replies change nothing", s.writes() == mark, "; ".join(s.since(mark)))
    await s.tick(3948.2)
    await s.tick(3932.5)
    await ch.post("Close everything", reply_to=follow)
    sig, trades = await s.record(ch, first)
    s.check("closed by the reply to the FOLLOW-UP message; signal CLOSED",
            not await s.orders(first) and sig.status == "CLOSED", sig.status)


@scenario("instant: no levels ever arrive")
async def _(s: Session):
    ch = s.channel("I-alone")
    await s.tick(3947.5)
    first = await ch.post("SELL GOLD NOW")
    o = await s.show(first)
    s.check("position protected by a temporary SL and a TP", len(o) == 1 and o[0]["stopLoss"] and o[0]["takeProfit"])
    s.check("its risk is at most half the budget", risk(s, o) <= budget(s) * 0.6, f"risk {risk(s, o):.2f}")
    await ch.post("Close", reply_to=first)
    s.check("still manageable by a reply", not await s.orders(first))


@scenario("runner: half on the TPs, half without TP; managed by the channel")
async def _(s: Session):
    ch = s.channel("N-runner")
    s.set(enable_runner_split=True, runner_share_percent=50.0)
    m = await running_sell(s, ch, "XAUUSD SELL 3950\n\nSL 3962\nTP1 3940\nTP2 3930")
    o = await s.show(m)
    run = [x for x in o if not x["takeProfit"]]
    s.check("TP orders on 3940 / 3930 plus one runner without TP, same SL",
            tps(o) == [3930.0, 3940.0] and len(run) == 1 and all_sl(o, 3962))
    s.check("runner is about half of the lots", run and abs(run[0]["volume"] - lots(o) / 2) <= 0.011,
            f"{run[0]['volume'] if run else 0} of {lots(o)}")
    s.check("whole setup within Max Risk Per Trade", *within_budget(s, o))
    await s.tick(3939.5)
    await s.tick(3929.5)
    o = await s.show(m)
    s.check("both TPs hit: only the runner is left, still without TP", len(o) == 1 and not o[0]["takeProfit"])
    await ch.post("SL to 3935, let it run")
    o = await s.show(m)
    s.check("plain \"SL to 3935\": runner SL 3935", all_sl(o, 3935, 0.8))
    await s.tick(3915.0)
    await ch.post("Close gold now")
    sig, trades = await s.record(ch, m)
    s.check("plain \"Close gold now\": runner closed below TP2, signal CLOSED",
            not await s.orders(m) and sig.status == "CLOSED" and s.bridge.closed[-1]["price_close"] < 3930)


@scenario("runner: off → on → off follows the setting")
async def _(s: Session):
    ch = s.channel("N-toggle")
    await s.tick(3945.0)
    a = await ch.post("XAUUSD SELL LIMIT 3952\nSL 3964\nTP 3942\nTP 3932")
    s.check("runner OFF: every order has a TP", all(x["takeProfit"] for x in await s.show(a)))
    await s.flatten()
    s.set(enable_runner_split=True)
    b = await ch.post("XAUUSD SELL LIMIT 3953\nSL 3965\nTP 3943\nTP 3933")
    s.check("runner ON: one order without TP", sum(1 for x in await s.show(b) if not x["takeProfit"]) == 1)
    await s.flatten()
    s.set(enable_runner_split=False)
    c = await ch.post("XAUUSD SELL LIMIT 3954\nSL 3966\nTP 3944\nTP 3934")
    s.check("runner OFF again: every order has a TP", all(x["takeProfit"] for x in await s.show(c)))


# ═════════════════════════════════════════════════════════════════════════════
# 9. Owner's channel rules, conditional plans
# ═════════════════════════════════════════════════════════════════════════════

@scenario("channel rule: owner's rule for a phrase the channel uses")
async def _(s: Session):
    ch = s.channel("U-rules")
    table = s.prisma.client.channelbehaviorrule
    await table.create(data={"channelId": str(ch.id), "channelTitle": ch.title, "ruleName": "Ignore hype",
                             "replyPattern": "to the moon", "patternType": "CONTAINS", "actionType": "IGNORE"})
    await table.create(data={"channelId": str(ch.id), "channelTitle": ch.title, "ruleName": "Secure = break-even",
                             "replyPattern": "secure", "patternType": "CONTAINS", "actionType": "BREAKEVEN"})
    m = await running_sell(s, ch)
    await s.tick(3944.0)
    mark = s.writes()
    await ch.post("Close it… just kidding, to the moon 🚀", reply_to=m)
    s.check("rule IGNORE: a reply containing \"to the moon\" does nothing", s.writes() == mark,
            "; ".join(s.since(mark)))
    await ch.post("Secure it guys", reply_to=m)
    s.check("rule BREAKEVEN: \"Secure it guys\" moves the setup to break-even", all_sl(await s.show(m), 3950, 0.8))


async def plan_of(s: Session, ch, msg_id: int):
    sig, _ = await s.record(ch, msg_id)
    return await s.prisma.client.tradeplan.find_first(where={"signalId": sig.id}) if sig else None


ZONE_PLAN = ("GOLD plan:\nWait for price to come back into the 3936 - 3940 zone, then BUY.\n"
             "SL 3930\nTP 3950\nTP 3960\nDo not enter before price is in the zone.")


@scenario("plan: wait-for-zone setup, owner executes it")
async def _(s: Session):
    ch = s.channel("U-plan-manual")
    s.set(plan_auto_execute=False)
    await s.tick(3945.0)
    mark = s.writes()
    m = await ch.post(ZONE_PLAN)
    plan = await plan_of(s, ch, m)
    if plan is None:
        from src.services.approval_queue import approval_queue
        waiting = approval_queue.get_all_pending()
        for item in waiting:
            approval_queue.reject_signal(item.signal_id, "end of scenario")
        s.finding("this time the AI read the wait-for-zone text as a signal, not a plan"
                  + ("; the safety gate held it for manual approval" if waiting else ""))
        s.check("nothing entered without the owner", not s.since(mark), "; ".join(s.since(mark)))
        return
    s.check("recognised as a plan (zone 3936–3940, SL 3930), nothing entered",
            plan is not None and near(plan.primaryEntryMin, 3936, 0.6) and near(plan.primaryEntryMax, 3940, 0.6)
            and near(plan.primarySl, 3930, 0.6) and not s.since(mark),
            f"{'no plan' if plan is None else f'{plan.primaryEntryMin}–{plan.primaryEntryMax} SL {plan.primarySl}'}")
    await s.tick(3938.0)
    s.check("price enters the zone, auto-execute off: still nothing entered", not s.since(mark),
            "; ".join(s.since(mark)))
    await s.prisma.client.tradeplan.update(where={"id": plan.id},
                                           data={"manualExecuteRequested": True, "manualExecuteLeg": "primary"})
    s.out("   owner presses Execute on the plan in the dashboard")
    await s.sync()
    s.report()
    placed = list(s.bridge.positions.values()) + list(s.bridge.orders.values())
    s.check("the plan is entered as a BUY with SL 3930 and its TPs",
            placed and all(p["type"] in (0, 2) and near(p["sl"], 3930, 0.6) for p in placed)
            and sorted({p["tp"] for p in placed}) == [3950.0, 3960.0],
            "; ".join(s.since(mark)) or "nothing placed")


@scenario("plan: wait-for-zone setup with auto-execute on")
async def _(s: Session):
    ch = s.channel("U-plan-auto")
    s.set(plan_auto_execute=True)
    await s.tick(3945.0)
    mark = s.writes()
    m = await ch.post(ZONE_PLAN)
    s.check("nothing entered while price is outside the zone", not s.since(mark), "; ".join(s.since(mark)))
    await s.tick(3938.0)
    await s.sync()
    s.report()
    placed = list(s.bridge.positions.values()) + list(s.bridge.orders.values())
    plan = await plan_of(s, ch, m)
    if placed:
        s.check("price enters the zone: the BUY is entered with SL 3930",
                all(p["type"] in (0, 2) and near(p["sl"], 3930, 0.6) for p in placed), "; ".join(s.since(mark)))
        s.check("sized within Max Risk Per Trade",
                sum(abs(p["price_open"] - p["sl"]) * 100 * p.get("volume", p.get("volume_current", 0)) for p in placed)
                <= budget(s) * 1.1)
    else:
        from src.services.approval_queue import approval_queue
        waiting = approval_queue.get_all_pending()
        if plan is not None:
            s.finding(f"PLAN_AUTO_EXECUTE on: the plan was stored with autoExecute={plan.autoExecute} "
                      f"(safety gate) and was not entered when price came into the zone")
        elif waiting:
            s.finding("PLAN_AUTO_EXECUTE on: this time the AI read the same text as a signal, not a plan; "
                      "the safety gate sent it for manual approval instead of entering")
            for item in waiting:
                approval_queue.reject_signal(item.signal_id, "end of scenario")
        else:
            s.finding("PLAN_AUTO_EXECUTE on: neither a plan nor an approval request was created")
        s.check("nothing entered without the owner", not s.since(mark), "; ".join(s.since(mark)))


@scenario("plan: breakout wording (\"if price breaks above 3960 we buy\")")
async def _(s: Session):
    ch = s.channel("U-plan-break")
    s.set(plan_auto_execute=True)
    await s.tick(3945.0)
    mark = s.writes()
    m = await ch.post("GOLD plan for today:\nIf price breaks above 3960 we BUY, SL 3950, TP 3975.\n"
                      "No entry before the break.")
    plan = await plan_of(s, ch, m)
    s.check("nothing entered before the break", not s.since(mark), "; ".join(s.since(mark)))
    await s.tick(3961.5)
    await s.sync()
    s.report()
    if s.since(mark):
        s.finding("breakout plan entered after the break: " + "; ".join(s.since(mark))[:150])
    elif plan is not None:
        s.finding(f"breakout plan is stored as the zone {plan.primaryEntryMin}–{plan.primaryEntryMax} "
                  f"(autoExecute={plan.autoExecute}); price jumped through it to 3961.5 and nothing was entered")
    else:
        s.finding("breakout wording was not stored as a plan")


async def main() -> int:
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")]
    chosen = [(n, f) for n, f in SCENARIOS if not wanted or any(w.lower() in n.lower() for w in wanted)]
    if "--list" in sys.argv:
        print("\n".join(n for n, _ in SCENARIOS))
        return 0
    s = Session(out=lambda line: print(line, flush=True))
    await s.start()
    print(f"AI: {s.settings_obj.primary_ai_provider.value} ({s.settings_obj.deepseek_model})  |  "
          f"broker: simulated MT5 bridge  |  {len(chosen)} scenario(s)")
    for name, fn in chosen:
        await s.run(name, fn)
    failed = s.summary()
    await s.stop()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
