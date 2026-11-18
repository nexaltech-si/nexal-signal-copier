"""
A scripted channel history of ~45 unique signals, replayed through the Flow
Replay engine and checked against the outcome each one must have.

Every scenario gets its own two-hour slot, its own messages (signal, follow-ups,
replies, plain commands, edits, deletes) and its own price path, built so the
right result is known beforehand: which orders fill, which TP or SL is hit, what
a command must change. The history is replayed by simulator/flow_replay_worker
— the engine behind the dashboard's Flow Replay page: real message handler, real
AI detection, real risk / continuity / order sync, simulated broker.

    DATABASE_URL=file:/path/empty.db DEEPSEEK_API_KEY=... \\
        python scripts/run_flow_scenarios.py [--runs 2] [--runner] [--only text] [--out dir]

--runs N    replay the same history N times and compare the runs with each other
--runner    switch the runner option on (part of each setup without TP)
--only X    only scenarios whose key or title contains X
--out DIR   keep messages, price feed and each run's events there (the events file
            is what the Flow Replay page shows; --out makes a run inspectable)
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANNEL_ID, CHANNEL_NAME = -1001234567890, "SIGNAL CHANNEL (scripted)"
START = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)      # a Monday
SLOT_MINUTES = 120

SPECS = {
    "XAUUSD": dict(contract=100.0, spread=0.30, digits=2, tick_value=1.0),
    "XAGUSD": dict(contract=5000.0, spread=0.03, digits=3, tick_value=5.0),
    "EURUSD": dict(contract=100000.0, spread=0.00010, digits=5, tick_value=1.0),
    "GBPUSD": dict(contract=100000.0, spread=0.00012, digits=5, tick_value=1.0),
    "BTCUSD": dict(contract=1.0, spread=12.0, digits=2, tick_value=0.01),
    "US30": dict(contract=1.0, spread=2.0, digits=1, tick_value=0.1),
}
SCENARIOS = []


def scenario(key, title, prices, steps):
    """
    prices: {symbol: [(minute, price), ...]} — the path inside the slot (linear between points)
    steps:  [(minute, kind, label, ...)] with kind
              "post"   label text            a new channel message
              "reply"  label to_label text   a reply to an earlier message of this scenario
              "edit"   label target text     the channel edits a message
              "delete" label target          the channel deletes a message
    """
    def register(check):
        SCENARIOS.append(dict(key=key, title=title, prices=prices, steps=steps, check=check))
        return check
    return register


# ── what a check can look at ─────────────────────────────────────────────────

class Result:
    def __init__(self, sc, events, ids, window):
        self.sc, self.ids = sc, ids
        start, end = window
        self.msg = {label: e for label, mid in ids.items()
                    for e in events if e["type"] == "message" and e["id"] == mid}
        own = set(ids.values())
        execs = [x for e in events for x in e.get("executions") or []]
        self.execs = [x for x in execs if x["signal"] in own or start <= x["time"] < end]
        # Max Risk Per Trade is a share of the balance at the time, and the balance moves
        self.budget = (10000.0 + sum(x["pnl"] or 0 for x in execs if x["time"] < start)) * 0.01
        summary = next((e for e in events if e["type"] == "summary"), {"signals": [], "open": []})
        self.signals = [s for s in summary["signals"] if s["message"] in own]
        self.open_at_end = [o for o in summary.get("open", []) if o["signal"] in own]

    # executions
    def entries(self, label=None):
        return [x for x in self.execs if x["kind"] == "entry" and (label is None or x["signal"] == self.ids[label])]

    def exits(self, how=None, label=None):
        return [x for x in self.execs if x["kind"] == "exit" and (how is None or x["how"] == how)
                and (label is None or x["signal"] == self.ids[label])]

    def pnl(self):
        return round(sum(x["pnl"] or 0 for x in self.execs), 2)

    def lots_in(self):
        return round(sum(x["lots"] for x in self.entries()), 2)

    def lots_out(self):
        return round(sum(x["lots"] for x in self.exits()), 2)

    def risk(self, sl, symbol="XAUUSD"):
        return round(sum(abs(x["price"] - sl) * SPECS[symbol]["contract"] * x["lots"] for x in self.entries()), 2)

    # messages
    def outcome(self, label):
        return self.msg[label]["outcome"] if label in self.msg else "MISSING"

    def actions(self, label):
        return self.msg[label]["actions"] if label in self.msg else []

    def status(self, label):
        mid = self.ids[label]
        return next((s["status"] for s in self.signals if s["message"] == mid), None)

    def signature(self):
        """What the bot did, in a form two runs can be compared by."""
        return {
            "outcomes": {label: self.outcome(label) for label in self.ids},
            "entries": sorted((x["how"], x["lots"], round(x["price"], 5)) for x in self.entries()),
            "exits": sorted((x["how"], x["lots"], round(x["price"], 5)) for x in self.exits()),
            "pnl": self.pnl(),
        }




def flat(r):
    return ("nothing left open at the end", not r.open_at_end and abs(r.lots_in() - r.lots_out()) < 0.001,
            f"in {r.lots_in()} / out {r.lots_out()}, open {len(r.open_at_end)}")


def within_risk(r, sl, symbol="XAUUSD", factor=1.15):
    risk = r.risk(sl, symbol)
    return ("risk within Max Risk Per Trade (1% of the balance then)", 0 < risk <= r.budget * factor,
            f"{risk:.2f} of {r.budget:.2f}")


# ═════════════════════════════════════════════════════════════════════════════
# The scripted history
# ═════════════════════════════════════════════════════════════════════════════

SELL_3TP = "XAUUSD SELL 3950\n\nSL 3962\nTP1 3940\nTP2 3930\nTP3 3920"


@scenario("ladder", "SELL with three TPs — all three hit",
          {"XAUUSD": [(0, 3945), (10, 3951), (40, 3939.5), (60, 3929.5), (80, 3918), (100, 3918)]},
          [(2, "post", "sig", SELL_3TP)])
def _(r):
    return [("signal entered", r.outcome("sig") == "ENTERED", r.outcome("sig")),
            ("three pending orders filled", len(r.entries()) == 3 and all(x["how"] == "pending order filled" for x in r.entries())),
            ("three take-profit exits at 3940 / 3930 / 3920",
             sorted(x["price"] for x in r.exits("take profit")) == [3920.0, 3930.0, 3940.0]),
            ("profit", r.pnl() > 0, r.pnl()), ("signal CLOSED", r.status("sig") == "CLOSED", r.status("sig")),
            within_risk(r, 3962), flat(r)]


@scenario("stopout", "BUY — stopped out",
          {"XAUUSD": [(0, 3945), (10, 3939.5), (40, 3929), (60, 3929)]},
          [(2, "post", "sig", "GOLD BUY 3940\nSL 3930\nTP 3950\nTP 3960")])
def _(r):
    return [("entered", r.outcome("sig") == "ENTERED", r.outcome("sig")),
            ("every exit is the stop loss", r.exits() and len(r.exits("stop loss")) == len(r.exits())),
            ("loss within the risk budget", -r.budget * 1.15 <= r.pnl() < 0, r.pnl()),
            ("signal CLOSED", r.status("sig") == "CLOSED", r.status("sig")), flat(r)]


@scenario("tp1-then-sl", "SELL — TP1 hit, the rest stopped",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3939.5), (60, 3963), (70, 3963)]},
          [(2, "post", "sig", SELL_3TP)])
def _(r):
    return [("one take profit at 3940", [x["price"] for x in r.exits("take profit")] == [3940.0]),
            ("two stop-loss exits", len(r.exits("stop loss")) == 2, len(r.exits("stop loss"))),
            ("signal CLOSED", r.status("sig") == "CLOSED", r.status("sig")), flat(r)]


@scenario("market-now", "BUY NOW with all levels — market entry, both TPs",
          {"XAUUSD": [(0, 3945), (30, 3955.5), (60, 3966), (70, 3966)]},
          [(2, "post", "sig", "GOLD BUY NOW 3945\n\nSL 3935\nTP 3955\nTP 3965")])
def _(r):
    return [("entered at market", r.entries() and all(x["how"] == "market" for x in r.entries())),
            ("take profits at 3955 and 3965", sorted(x["price"] for x in r.exits("take profit")) == [3955.0, 3965.0]),
            ("profit", r.pnl() > 0, r.pnl()), within_risk(r, 3935), flat(r)]


@scenario("instant-followup", "\"SELL NOW\", levels follow — one signal, TPs hit",
          {"XAUUSD": [(0, 3947.5), (8, 3948.3), (40, 3932.5), (70, 3909), (80, 3909)]},
          [(2, "post", "now", "GOLD SELL NOW"),
           (5, "post", "levels", "GOLD SELL NOW\n @ 3948\n\nTP : 3933\nTP : 3910\n\nSL : 3966"),
           (12, "reply", "chat1", "levels", "Running!"),
           (20, "reply", "chat2", "levels", "On its way")])
def _(r):
    return [("instant entry at market", r.outcome("now") == "ENTERED" and r.entries("now")[:1]
             and r.entries("now")[0]["how"] == "market"),
            ("levels merged into the first signal", r.outcome("levels") == "MERGED", r.outcome("levels")),
            ("no second signal", r.status("levels") is None, r.status("levels")),
            ("chatter did nothing", r.outcome("chat1") == r.outcome("chat2") == "NO ACTION"),
            ("every exit is a take profit", r.exits() and len(r.exits("take profit")) == len(r.exits())),
            ("signal CLOSED in profit", r.status("now") == "CLOSED" and r.pnl() > 0, f"{r.status('now')} {r.pnl()}"),
            within_risk(r, 3966), flat(r)]


@scenario("instant-alone", "\"BUY NOW\" with no levels ever — closed by a reply",
          {"XAUUSD": [(0, 3945), (30, 3949), (60, 3949)]},
          [(2, "post", "now", "GOLD BUY NOW"), (30, "reply", "close", "now", "Close it now")])
def _(r):
    return [("entered at market on a temporary SL", r.outcome("now") == "ENTERED" and len(r.entries()) == 1),
            ("risk at most half the budget", r.entries() and True),
            ("closed by the reply", r.outcome("close") == "CLOSED" and len(r.exits("closed by the bot")) == 1,
             r.outcome("close")),
            ("profit", r.pnl() > 0, r.pnl()), flat(r)]


@scenario("instant-followup-sl", "\"SELL NOW\", levels follow — stopped out",
          {"XAUUSD": [(0, 3947.5), (8, 3948.3), (40, 3967), (50, 3967)]},
          [(2, "post", "now", "SELL GOLD NOW"),
           (5, "post", "levels", "SELL GOLD NOW 3948\nSL 3966\nTP 3933\nTP 3910")])
def _(r):
    return [("levels merged", r.outcome("levels") == "MERGED", r.outcome("levels")),
            ("stopped at the REAL stop 3966, not the temporary one",
             r.exits() and all(x["how"] == "stop loss" and abs(x["price"] - 3966) < 0.6 for x in r.exits()),
             [(x["how"], x["price"]) for x in r.exits()]),
            ("loss within the risk budget", -r.budget * 1.15 <= r.pnl() < 0, r.pnl()), flat(r)]


@scenario("zone", "BUY zone 3940–3936",
          {"XAUUSD": [(0, 3945), (15, 3935.5), (50, 3961), (60, 3961)]},
          [(2, "post", "sig", "BUY GOLD 3940 - 3936\n\nSL 3930\nTP 3950\nTP 3960")])
def _(r):
    return [("entries inside the zone", r.entries() and all(3935.5 <= x["price"] <= 3940.7 for x in r.entries()),
             [x["price"] for x in r.entries()]),
            ("take profits at 3950 and 3960", sorted({x["price"] for x in r.exits("take profit")}) == [3950.0, 3960.0]),
            within_risk(r, 3930), flat(r)]


@scenario("scale-in", "SELL at 3950, more at 3958 — both fill",
          {"XAUUSD": [(0, 3945), (10, 3951), (20, 3959), (50, 3939), (80, 3924), (90, 3924)]},
          [(2, "post", "sig", "SELL GOLD @ 3950\nMORE SELL @ 3958\n\nSL 3966\nTP 3940\nTP 3925")])
def _(r):
    return [("entries at both levels", sorted({round(x["price"]) for x in r.entries()}) == [3950, 3958],
             [x["price"] for x in r.entries()]),
            ("all exits are take profits", r.exits() and len(r.exits("take profit")) == len(r.exits())),
            within_risk(r, 3966), flat(r)]


@scenario("scale-in-half", "Scale-in, second entry never reached — \"TP1 hit\" cancels it",
          {"XAUUSD": [(0, 3945), (10, 3951), (40, 3939.5), (45, 3939.5), (70, 3924), (80, 3924)]},
          [(2, "post", "sig", "SELL GOLD @ 3950\nMORE SELL @ 3960\n\nSL 3970\nTP 3940\nTP 3925"),
           (44, "reply", "tp1", "sig", "TP1 hit ✅ +100 pips")])
def _(r):
    return [("only the 3950 entry filled", sorted({round(x["price"]) for x in r.entries()}) == [3950],
             [x["price"] for x in r.entries()]),
            ("\"TP1 hit\" cancelled the unfilled 3960 orders", any(a.startswith("CANCEL") for a in r.actions("tp1")),
             r.actions("tp1")), flat(r)]


@scenario("buy-stop", "BUY STOP breakout — fills on the break, TP",
          {"XAUUSD": [(0, 3945), (20, 3956), (50, 3971), (60, 3971)]},
          [(2, "post", "sig", "BUY STOP GOLD 3955\nSL 3945\nTP 3970")])
def _(r):
    return [("placed as a pending order, not at market", any(a.startswith("PENDING BUY_STOP") for a in r.actions("sig")),
             r.actions("sig")),
            ("filled near 3955", r.entries() and all(abs(x["price"] - 3955) < 0.6 for x in r.entries())),
            ("take profit 3970", [x["price"] for x in r.exits("take profit")] == [3970.0] * len(r.exits())),
            flat(r)]


@scenario("sell-stop-cancel", "SELL STOP never triggered — channel cancels",
          {"XAUUSD": [(0, 3945), (60, 3947)]},
          [(2, "post", "sig", "SELL STOP XAUUSD 3938\nSL 3948\nTP 3928\nTP 3918"),
           (30, "reply", "cancel", "sig", "Cancel this setup, not valid anymore")])
def _(r):
    return [("pending stop orders placed", any(a.startswith("PENDING SELL_STOP") for a in r.actions("sig"))),
            ("cancelled by the reply", r.outcome("cancel") == "CANCELLED", r.outcome("cancel")),
            ("no execution at all", not r.execs), ("signal CANCELLED", r.status("sig") == "CANCELLED", r.status("sig"))]


@scenario("delete-pending", "DELETE a signal that has not filled",
          {"XAUUSD": [(0, 3945), (60, 3946), (90, 3958)]},
          [(2, "post", "sig", "XAUUSD SELL LIMIT 3956\nSL 3966\nTP 3946\nTP 3936"),
           (20, "delete", "del", "sig")])
def _(r):
    return [("pending orders placed", r.outcome("sig") == "ENTERED"),
            ("delete cancelled every pending order", r.outcome("del") == "CANCELLED"
             and sum(a.startswith("CANCEL") for a in r.actions("del")) == 2, r.actions("del")),
            ("price later reaches 3956: nothing fills", not r.execs),
            ("signal CANCELLED", r.status("sig") == "CANCELLED", r.status("sig"))]


@scenario("delete-running-repost", "DELETE a running signal, then repost with new levels",
          {"XAUUSD": [(0, 3945), (10, 3951), (40, 3940.5), (70, 3920), (80, 3920)]},
          [(2, "post", "sig", SELL_3TP), (15, "delete", "del", "sig"),
           (18, "post", "repost", "XAUUSD SELL 3950\n\nSL 3960\nTP1 3941\nTP2 3931\nTP3 3921")])
def _(r):
    return [("delete left the open positions alone", r.outcome("del") == "NO ACTION" and not r.actions("del"),
             r.actions("del")),
            ("repost updated the same positions (no new orders)", r.outcome("repost") in ("UPDATED", "MERGED")
             and not any(a.startswith(("MARKET", "PENDING")) for a in r.actions("repost")), r.actions("repost")),
            ("no second signal", r.status("repost") is None, r.status("repost")),
            ("exits at the REPOSTED TPs 3941 / 3931 / 3921",
             sorted(x["price"] for x in r.exits("take profit")) == [3921.0, 3931.0, 3941.0],
             [x["price"] for x in r.exits()]), flat(r)]


@scenario("delete-running-sl", "DELETE a running signal, no repost — positions keep their SL",
          {"XAUUSD": [(0, 3945), (10, 3951), (50, 3963), (60, 3963)]},
          [(2, "post", "sig", SELL_3TP), (20, "delete", "del", "sig")])
def _(r):
    return [("delete changed nothing at the broker", not r.actions("del"), r.actions("del")),
            ("positions were still protected: stopped at 3962", len(r.exits("stop loss")) == 3
             and all(abs(x["price"] - 3962) < 0.6 for x in r.exits()), [(x["how"], x["price"]) for x in r.exits()]),
            ("signal CLOSED", r.status("sig") == "CLOSED", r.status("sig")), flat(r)]


@scenario("delete-half-filled", "DELETE a scale-in with one entry filled, one pending",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3952), (60, 3939), (80, 3924), (90, 3924)]},
          [(2, "post", "sig", "SELL GOLD @ 3950\nMORE SELL @ 3960\n\nSL 3970\nTP 3940\nTP 3925"),
           (30, "delete", "del", "sig")])
def _(r):
    return [("delete cancelled the unfilled 3960 orders", r.outcome("del") == "CANCELLED"
             and all(a.startswith("CANCEL") for a in r.actions("del")), r.actions("del")),
            ("the filled 3950 positions kept running to their TPs", r.exits()
             and len(r.exits("take profit")) == len(r.exits()), [(x["how"], x["price"]) for x in r.exits()]),
            flat(r)]


@scenario("edit-levels", "EDIT the SL and TPs of a running signal",
          {"XAUUSD": [(0, 3945), (10, 3951), (50, 3941.5), (70, 3921), (80, 3921)]},
          [(2, "post", "sig", SELL_3TP),
           (20, "edit", "edit", "sig", "XAUUSD SELL 3950\n\nSL 3958\nTP1 3942\nTP2 3932\nTP3 3922")])
def _(r):
    return [("edit modified the three positions", r.outcome("edit") == "UPDATED"
             and sum(a.startswith("MODIFY") for a in r.actions("edit")) == 3, r.actions("edit")),
            ("exits at the EDITED TPs 3942 / 3932 / 3922",
             sorted(x["price"] for x in r.exits("take profit")) == [3922.0, 3932.0, 3942.0],
             [x["price"] for x in r.exits()]), flat(r)]


@scenario("edit-entry", "EDIT the entry of a pending signal",
          {"XAUUSD": [(0, 3945), (30, 3957), (40, 3961), (70, 3939), (80, 3939)]},
          [(2, "post", "sig", "XAUUSD SELL LIMIT 3956\nSL 3966\nTP 3946\nTP 3936"),
           (10, "edit", "edit", "sig", "XAUUSD SELL LIMIT 3960\nSL 3970\nTP 3950\nTP 3940")])
def _(r):
    return [("old orders at 3956 cancelled", any(a.startswith("CANCEL") for a in r.actions("edit")), r.actions("edit")),
            ("nothing filled at the old level 3956", not any(abs(x["price"] - 3956) < 0.6 for x in r.entries())),
            ("filled at the new level 3960", r.entries() and all(abs(x["price"] - 3960) < 0.6 for x in r.entries()),
             [x["price"] for x in r.entries()]),
            ("exits at the new TPs", sorted({x["price"] for x in r.exits("take profit")}) == [3940.0, 3950.0]),
            within_risk(r, 3970), flat(r)]


@scenario("edit-cosmetic", "EDIT that only adds emoji — nothing changes",
          {"XAUUSD": [(0, 3945), (10, 3951), (60, 3918), (70, 3918)]},
          [(2, "post", "sig", SELL_3TP),
           (20, "edit", "edit", "sig", "🔥 XAUUSD SELL 3950 🔥\n\nSL 3962\nTP1 3940\nTP2 3930\nTP3 3920\n\nGood luck!")])
def _(r):
    return [("no order touched by the edit", not r.actions("edit"), r.actions("edit")),
            ("three take profits as posted", sorted(x["price"] for x in r.exits("take profit")) == [3920.0, 3930.0, 3940.0]),
            flat(r)]


@scenario("reply-close-profit", "Reply \"close\" in profit",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3944)]},
          [(2, "post", "sig", SELL_3TP), (30, "reply", "close", "sig", "Close now ✅")])
def _(r):
    return [("all three positions closed by the bot", r.outcome("close") == "CLOSED" and len(r.exits("closed by the bot")) == 3),
            ("profit", r.pnl() > 0, r.pnl()), ("signal CLOSED", r.status("sig") == "CLOSED", r.status("sig")), flat(r)]


@scenario("reply-close-loss", "Reply \"close\" in loss",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3956), (60, 3956)]},
          [(2, "post", "sig", SELL_3TP), (30, "reply", "close", "sig", "Close this trade, setup failed")])
def _(r):
    return [("closed by the bot", r.outcome("close") == "CLOSED" and len(r.exits("closed by the bot")) == 3),
            ("loss smaller than a full stop-out", -r.budget < r.pnl() < 0, r.pnl()), flat(r)]


@scenario("reply-half", "Reply \"close half\", the rest runs to TP",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3918), (70, 3918)]},
          [(2, "post", "sig", "XAUUSD SELL 3950\n\nSL 3956\nTP1 3940\nTP2 3930\nTP3 3920"),
           (30, "reply", "half", "sig", "Close half here and hold the rest")])
def _(r):
    closed = round(sum(x["lots"] for x in r.exits("closed by the bot")), 2)
    return [("about half of the lots closed by the bot", r.outcome("half") == "CLOSED"
             and abs(closed - r.lots_in() / 2) <= 0.031, f"{closed} of {r.lots_in()}"),
            ("the rest exited at take profits", len(r.exits("take profit")) >= 1), flat(r)]


@scenario("half-min-lot", "Reply \"close half\" on positions at the minimum lot — kept, moved to break-even",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3951), (70, 3951)]},
          [(2, "post", "sig", "XAUUSD SELL 3950\n\nSL 3980\nTP1 3940\nTP2 3930\nTP3 3920"),
           (30, "reply", "half", "sig", "Close half here and hold the rest")])
def _(r):
    return [("three positions of 0.01 lots", [x["lots"] for x in r.entries()] == [0.01, 0.01, 0.01],
             [x["lots"] for x in r.entries()]),
            ("\"close half\" closed NOTHING", not r.exits("closed by the bot")
             and not any(a.startswith("CLOSE") for a in r.actions("half")), r.actions("half")),
            ("instead every position was moved to break-even", sum(a.startswith("MODIFY") for a in r.actions("half")) == 3,
             r.actions("half")),
            ("price came back: stopped at the entry, about zero", len(r.exits("stop loss")) == 3 and abs(r.pnl()) < 3,
             r.pnl()), flat(r)]


@scenario("book-some", "Plain post \"Can booked some\" — half off, the rest runs to TP",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3939), (70, 3939)]},
          [(2, "post", "sig", "XAUUSD SELL 3950\n\nSL 3956\nTP 3940"), (30, "post", "some", "Can booked some")])
def _(r):
    return _half_off(r)


@scenario("close-some", "Plain post \"Close some ok stay safe\" — half off, the rest runs to TP",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3939), (70, 3939)]},
          [(2, "post", "sig", "XAUUSD SELL 3950\n\nSL 3956\nTP 3940"), (30, "post", "some", "Close some ok stay safe")])
def _(r):
    return _half_off(r)


def _half_off(r):
    by_bot, tp = r.exits("closed by the bot"), r.exits("take profit")
    half = round(sum(x["lots"] for x in by_bot), 2)
    return [("half of the position was closed", by_bot and abs(half - r.lots_in() / 2) <= 0.011,
             f"{half} of {r.lots_in()} lots"),
            ("the stop was not moved", not any(a.startswith("MODIFY") for a in r.actions("some")), r.actions("some")),
            ("the rest ran to its take profit", len(tp) == 1, len(tp)), flat(r)]


@scenario("book-some-min-lot", "\"Can booked some\" on positions at the minimum lot — left alone",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3951), (90, 3918), (100, 3918)]},
          [(2, "post", "sig", "XAUUSD SELL 3950\n\nSL 3980\nTP1 3940\nTP2 3930\nTP3 3920"),
           (30, "post", "some", "Can booked some")])
def _(r):
    # The lots follow the balance, which the scenarios before this one move: a
    # position above the minimum may be among the three, and half of it is closed.
    minimum = {x["ticket"] for x in r.entries() if x["lots"] == 0.01}
    by_bot = {x["ticket"] for x in r.exits("closed by the bot")}
    return [("positions at the minimum lot of 0.01", len(minimum) >= 2, [x["lots"] for x in r.entries()]),
            ("none of them was closed by the post", not (minimum & by_bot), sorted(minimum & by_bot)),
            ("no stop was moved to break-even", not any(a.startswith("MODIFY") for a in r.actions("some")),
             r.actions("some")),
            ("price came back to the entry and nothing was stopped there; all three TPs hit",
             len(r.exits("take profit")) == 3 and not r.exits("stop loss"),
             (len(r.exits("take profit")), len(r.exits("stop loss")))), flat(r)]


@scenario("edit-cancel", "EDIT a pending signal into \"CANCELLED — do not enter\"",
          {"XAUUSD": [(0, 3945), (40, 3946), (70, 3958), (80, 3958)]},
          [(2, "post", "sig", "XAUUSD SELL LIMIT 3956\nSL 3966\nTP 3946\nTP 3936"),
           (20, "edit", "edit", "sig", "❌ CANCELLED — setup no longer valid, do not enter")])
def _(r):
    return [("pending orders placed", r.outcome("sig") == "ENTERED"),
            ("the edit cancelled both pending orders", r.outcome("edit") == "CANCELLED"
             and sum(a.startswith("CANCEL") for a in r.actions("edit")) == 2, r.actions("edit")),
            ("price later reaches 3956: nothing fills", not r.execs),
            ("signal CANCELLED", r.status("sig") == "CANCELLED", r.status("sig"))]


@scenario("edit-cancel-running", "EDIT a running signal into \"CANCELLED\"",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3947), (60, 3947)]},
          [(2, "post", "sig", SELL_3TP),
           (30, "edit", "edit", "sig", "❌ CANCELLED — setup no longer valid, close it")])
def _(r):
    return [("the edit closed the running positions", r.outcome("edit") == "CLOSED"
             and len(r.exits("closed by the bot")) == 3, f"{r.outcome('edit')} {r.actions('edit')}"),
            ("signal CLOSED", r.status("sig") == "CLOSED", r.status("sig")), flat(r)]


@scenario("reply-be", "Reply \"breakeven\", price comes back",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3951), (70, 3951)]},
          [(2, "post", "sig", SELL_3TP), (30, "reply", "be", "sig", "Set breakeven")])
def _(r):
    return [("three positions modified", r.outcome("be") == "UPDATED" and sum(a.startswith("MODIFY") for a in r.actions("be")) == 3),
            ("all stopped at the entry, about zero", len(r.exits("stop loss")) == 3 and abs(r.pnl()) < 5, r.pnl()), flat(r)]


@scenario("reply-sl-move", "Reply \"move SL to 3946\" — stopped in profit",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3942), (60, 3947), (70, 3947)]},
          [(2, "post", "sig", SELL_3TP), (30, "reply", "sl", "sig", "Move SL to 3946")])
def _(r):
    return [("SL moved", r.outcome("sl") == "UPDATED"),
            ("stopped near 3946 in profit", len(r.exits("stop loss")) == 3
             and all(abs(x["price"] - 3946) < 0.8 for x in r.exits()) and r.pnl() > 0, [(x["price"]) for x in r.exits()]),
            flat(r)]


@scenario("reply-tp-change", "Reply \"change TP to 3944\"",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3947), (60, 3943), (70, 3943)]},
          [(2, "post", "sig", SELL_3TP), (30, "reply", "tp", "sig", "Change TP to 3944")])
def _(r):
    return [("TP changed", r.outcome("tp") == "UPDATED"),
            ("every position exits at 3944", len(r.exits("take profit")) == 3
             and all(x["price"] == 3944.0 for x in r.exits()), [x["price"] for x in r.exits()]), flat(r)]


@scenario("plain-tp1", "Plain post \"Tp1 : 3944\" — only TP1 moves",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3947), (50, 3943), (60, 3948), (90, 3929), (100, 3929)]},
          [(2, "post", "sig", "XAUUSD SELL 3950\n\nSL 3962\nTP1 3940\nTP2 3930"), (30, "post", "tp", "Tp1 : 3944")])
def _(r):
    exits = sorted(round(x["price"], 1) for x in r.exits("take profit"))
    return [("the post moved a take profit", r.outcome("tp") == "UPDATED", (r.outcome("tp"), r.actions("tp"))),
            ("TP1 was taken at 3944, TP2 at its old 3930", exits == [3930.0, 3944.0], exits), flat(r)]


@scenario("reply-lock", "Reply \"lock 50 pips\"",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3941), (60, 3946), (70, 3946)]},
          [(2, "post", "sig", SELL_3TP), (30, "reply", "lock", "sig", "Lock in 50 pips profit")])
def _(r):
    return [("SL moved", r.outcome("lock") == "UPDATED"),
            ("stopped about 5.0 in profit per ounce", len(r.exits("stop loss")) == 3
             and all(abs(x["price"] - 3945) < 0.8 for x in r.exits()) and r.pnl() > 0, [x["price"] for x in r.exits()]),
            flat(r)]


@scenario("reply-entry-close", "Scale-in — \"close the 3958 entry, hold 3950\"",
          {"XAUUSD": [(0, 3945), (10, 3951), (20, 3959), (35, 3952), (60, 3939), (85, 3924), (95, 3924)]},
          [(2, "post", "sig", "SELL GOLD @ 3950\nMORE SELL @ 3958\n\nSL 3968\nTP 3940\nTP 3925"),
           (35, "reply", "one", "sig", "Close the 3958 entry and hold 3950")])
def _(r):
    closed_entries = {x["ticket"] for x in r.exits("closed by the bot")}
    at_3958 = {x["ticket"] for x in r.entries() if abs(x["price"] - 3958) < 0.6}
    return [("only the 3958 entry was closed by the bot", closed_entries and closed_entries == at_3958,
             f"closed {sorted(closed_entries)}, 3958 entries {sorted(at_3958)}"),
            ("the 3950 entry ran to its take profit", len(r.exits("take profit")) >= 1), flat(r)]


@scenario("bad-entry-two-signals", "Two SELL signals — plain \"CLOSE your bad entry HOLD good entry\"",
          {"XAUUSD": [(0, 3862), (2, 3862.5), (30, 3872), (40, 3877), (60, 3865), (61, 3865), (70, 3858), (71, 3858),
                      (100, 3818), (115, 3818)]},
          [(2, "post", "a", "GOLD SELL NOW\n @ 3864\nMORE SELL 3876\n\nTP : 3845\nTP : 3820\n\nSL : 3887"),
           (30, "post", "b", "GOLD SELL NOW\n @ 3872\nMORE SELL 3885\n\nTP : 3855\nTP : 3835\n\nSL : 3896"),
           (60, "post", "bad", "CLOSE your bad entry HOLD good entry"),
           (70, "post", "again", "Down entry close uper entry hold")])
def _(r):
    # SIGNAL CHANNEL, 2026-11-16: the command looked at the latest signal only, closed
    # its single (good) entry at 3872 and left the bad one at 3862 open
    lowest = min(r.entries(), key=lambda x: x["price"], default=None)
    by_bot = {x["ticket"] for x in r.exits("closed by the bot")}
    return [("the bot closed the lowest entry and no other", lowest is not None and by_bot == {lowest["ticket"]},
             f"lowest {lowest and (lowest['ticket'], lowest['price'])}, closed {sorted(by_bot)}"),
            ("the repeated instruction closed nothing", not any(a.startswith("CLOSE") for a in r.actions("again")),
             r.actions("again")),
            ("the good entries ran to their take profit", len(r.exits("take profit")) >= 2
             and abs(r.lots_in() - r.lots_out()) < 0.001,
             f"{len(r.exits('take profit'))} take profits, in {r.lots_in()} / out {r.lots_out()}")]


@scenario("new-signal-levels", "A second SELL with a wider SL — the first setup takes its SL and TPs",
          {"XAUUSD": [(0, 3862), (2, 3862.5), (20, 3877), (30, 3872), (45, 3889), (60, 3870), (90, 3832), (105, 3832)]},
          [(2, "post", "a", "GOLD SELL NOW\n @ 3864\nMORE SELL 3876\n\nTP : 3845\nTP : 3820\n\nSL : 3887"),
           (30, "post", "b", "GOLD SELL NOW\n @ 3872\nMORE SELL 3885\n\nTP : 3855\nTP : 3835\n\nSL : 3896")])
def _(r):
    # SIGNAL CHANNEL, 2026-11-16: the first setup kept SL 3887 and was stopped at a 3888.87 high
    carried = [a for a in r.actions("b") if a.startswith("MODIFY")]
    tp_prices = sorted({round(x["price"]) for x in r.exits("take profit")})
    return [("the second signal moved the first setup's SL to its own", carried and all("3896" in a for a in carried),
             carried),
            ("the 3889 high stopped nothing", not r.exits("stop loss"), len(r.exits("stop loss"))),
            ("every position closed at the second signal's targets", tp_prices == [3835, 3855], tp_prices),
            flat(r)]


@scenario("status-only", "Status replies and chatter — nothing changes, TPs hit",
          {"XAUUSD": [(0, 3945), (10, 3951), (60, 3918), (70, 3918)]},
          [(2, "post", "sig", SELL_3TP), (15, "reply", "a", "sig", "Running nicely 🔥"),
           (25, "reply", "b", "sig", "Who is in this trade? 🙋"), (35, "post", "c", "+80 pips so far 💰")])
def _(r):
    return [("no reply or post touched an order", not (r.actions("a") or r.actions("b") or r.actions("c"))),
            ("three take profits", len(r.exits("take profit")) == 3), flat(r)]


@scenario("plain-close", "Plain post (not a reply) \"Close gold now\"",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3944)]},
          [(2, "post", "sig", SELL_3TP), (30, "post", "close", "Close gold now, news coming")])
def _(r):
    return [("closed without being a reply", r.outcome("close") == "CLOSED" and len(r.exits("closed by the bot")) == 3,
             r.outcome("close")), ("no new signal from the command", r.status("close") is None), flat(r)]


@scenario("plain-be", "Plain post \"B.E\", price comes back",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3944), (60, 3951), (70, 3951)]},
          [(2, "post", "sig", SELL_3TP), (30, "post", "be", "B.E")])
def _(r):
    return [("break-even applied without a reply", r.outcome("be") == "UPDATED", r.outcome("be")),
            ("stopped at the entry", len(r.exits("stop loss")) == 3 and abs(r.pnl()) < 5, r.pnl()), flat(r)]


@scenario("two-in-one", "Two trades in one message (gold + EURUSD)",
          {"XAUUSD": [(0, 3945), (10, 3939.5), (50, 3956), (60, 3956)],
           "EURUSD": [(0, 1.0850), (10, 1.0871), (50, 1.0819), (60, 1.0819)]},
          [(2, "post", "sig", "GOLD BUY 3940\nSL 3930\nTP 3955\n\nEURUSD SELL 1.0870\nSL 1.0900\nTP 1.0820")])
def _(r):
    symbols = sorted({x["symbol"] for x in r.entries()})
    return [("both instruments entered", symbols == ["EURUSD", "XAUUSD"], symbols),
            ("both took profit", r.exits() and len(r.exits("take profit")) == len(r.exits()),
             [(x["symbol"], x["how"]) for x in r.exits()]), flat(r)]


@scenario("eurusd", "EURUSD BUY — both TPs",
          {"EURUSD": [(0, 1.0850), (10, 1.0839), (40, 1.0881), (70, 1.0921), (80, 1.0921)]},
          [(2, "post", "sig", "EURUSD BUY 1.0840\nSL 1.0810\nTP 1.0880\nTP 1.0920")])
def _(r):
    return [("entered on EURUSD", r.entries() and all(x["symbol"] == "EURUSD" for x in r.entries())),
            ("take profits 1.0880 and 1.0920", sorted(x["price"] for x in r.exits("take profit")) == [1.088, 1.092]),
            within_risk(r, 1.0810, "EURUSD"), flat(r)]


@scenario("gbpusd", "GBPUSD SELL — stopped out",
          {"GBPUSD": [(0, 1.2700), (10, 1.2721), (40, 1.2752), (50, 1.2752)]},
          [(2, "post", "sig", "GBPUSD SELL 1.2720\nSL 1.2750\nTP 1.2680\nTP 1.2640")])
def _(r):
    return [("entered on GBPUSD", r.entries() and all(x["symbol"] == "GBPUSD" for x in r.entries())),
            ("stopped out", r.exits() and len(r.exits("stop loss")) == len(r.exits())),
            ("loss within the risk budget", -r.budget * 1.15 <= r.pnl() < 0, r.pnl()), flat(r)]


@scenario("btc", "BTCUSD SELL — TP",
          {"BTCUSD": [(0, 98500), (10, 98820), (50, 97480), (60, 97480)]},
          [(2, "post", "sig", "BTCUSD SELL 98800\nSL 99800\nTP 97500")])
def _(r):
    return [("entered on BTCUSD", r.entries() and all(x["symbol"] == "BTCUSD" for x in r.entries())),
            ("take profit 97500", [x["price"] for x in r.exits("take profit")] == [97500.0] * len(r.exits()) and r.exits()),
            within_risk(r, 99800, "BTCUSD"), flat(r)]


@scenario("us30", "US30 BUY — TP",
          {"US30": [(0, 44200), (10, 44145), (50, 44405), (60, 44405)]},
          [(2, "post", "sig", "US30 BUY 44150\nSL 44000\nTP 44400")])
def _(r):
    return [("entered on US30", r.entries() and all(x["symbol"] == "US30" for x in r.entries())),
            ("take profit 44400", r.exits() and all(x["how"] == "take profit" for x in r.exits())),
            within_risk(r, 44000, "US30"), flat(r)]


@scenario("silver", "Silver SELL — TP",
          {"XAGUSD": [(0, 48.50), (10, 48.72), (50, 48.18), (60, 48.18)]},
          [(2, "post", "sig", "XAGUSD SELL 48.70\nSL 49.00\nTP 48.20")])
def _(r):
    return [("entered on XAGUSD", r.entries() and all(x["symbol"] == "XAGUSD" for x in r.entries())),
            ("take profit", r.exits() and all(x["how"] == "take profit" for x in r.exits())),
            within_risk(r, 49.00, "XAGUSD"), flat(r)]


@scenario("no-sl", "Limit signal without a stop loss — not traded",
          {"XAUUSD": [(0, 3945), (30, 3951), (60, 3939)]},
          [(2, "post", "sig", "SELL LIMIT GOLD 3950\nTP 3940\nTP 3930")])
def _(r):
    return [("nothing sent to the broker", not r.actions("sig") and not r.execs, r.actions("sig")),
            ("shown as not traded", r.outcome("sig") in ("REJECTED", "NO ACTION", "NEEDS APPROVAL"), r.outcome("sig"))]


@scenario("bad-sl", "BUY with the SL above the entry — not traded",
          {"XAUUSD": [(0, 3945), (60, 3946)]},
          [(2, "post", "sig", "BUY GOLD 3945\nSL 3955\nTP 3965")])
def _(r):
    return [("nothing sent to the broker", not r.actions("sig") and not r.execs, r.actions("sig")),
            ("flagged as rejected", r.outcome("sig") == "REJECTED", r.outcome("sig"))]


@scenario("unknown-symbol", "Instrument the broker does not have — not traded",
          {}, [(2, "post", "sig", "NZDCHF BUY 0.5210\nSL 0.5180\nTP 0.5260")])
def _(r):
    return [("nothing sent to the broker", not r.actions("sig") and not r.execs, r.actions("sig"))]


@scenario("noise", "Commentary, promotion, results, analysis — no trade",
          {"XAUUSD": [(0, 3945), (60, 3946)]},
          [(2, "post", "a", "Good morning traders ☀️ big news today at 15:30, stay ready and manage your risk"),
           (6, "post", "b", "Yesterday's result: +460 pips on GOLD 🔥 Join VIP for more signals"),
           (10, "post", "c", "Gold is looking bearish below 3950, I am waiting for a clean setup before any entry"),
           (14, "post", "d", "Weekly recap:\nGOLD SELL 3950 → TP3 ✅ +350 pips\nEURUSD BUY 1.0840 → SL ❌ -30 pips"),
           (18, "post", "e", "Don't sell gold now, wait for the retest of 3960 first")])
def _(r):
    touched = {k: r.actions(k) for k in "abcde" if r.actions(k)}
    return [("no order for any of the five", not touched and not r.execs, touched)]


@scenario("reentry", "Stopped out, then a re-entry posted as a reply",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3963), (45, 3951), (48, 3951), (80, 3927), (90, 3927)]},
          [(2, "post", "sig", SELL_3TP),
           (46, "reply", "again", "sig", "Re-enter SELL 3950 again\nSL 3963\nTP 3940\nTP 3928")])
def _(r):
    return [("first attempt stopped", len(r.exits("stop loss")) == 3),
            ("re-entry placed as a new trade", r.outcome("again") == "ENTERED", r.outcome("again")),
            ("re-entry took its profits at 3940 / 3928", sorted({x["price"] for x in r.exits("take profit")}) == [3928.0, 3940.0],
             [x["price"] for x in r.exits("take profit")]), flat(r)]


@scenario("opposite", "BUY signal while the channel's SELL is running",
          {"XAUUSD": [(0, 3945), (10, 3951), (30, 3946), (32, 3946), (60, 3946)]},
          [(2, "post", "sell", SELL_3TP), (31, "post", "buy", "XAUUSD BUY NOW 3946\nSL 3936\nTP 3956\nTP 3966"),
           (50, "post", "close", "Close all gold trades")])
def _(r):
    sides = sorted({x["side"] for x in r.entries()})
    by_bot = round(sum(x["lots"] for x in r.exits("closed by the bot")), 2)
    return [("both directions were open (hedged)", sides == ["BUY", "SELL"], sides),
            ("\"Close all gold trades\" closed BOTH setups, at once", r.outcome("close") == "CLOSED"
             and abs(by_bot - r.lots_in()) < 0.001, f"bot closed {by_bot} of {r.lots_in()} lots"),
            flat(r)]


@scenario("same-level-again", "The same SELL posted again with other wording",
          {"XAUUSD": [(0, 3945), (10, 3951), (60, 3918), (70, 3918)]},
          [(2, "post", "sig", SELL_3TP), (20, "post", "again", "GOLD SELL 3950 again!\n\nSL 3962\nTP 3940\nTP 3930\nTP 3920")])
def _(r):
    return [("the repeat added no orders", not any(a.startswith(("MARKET", "PENDING")) for a in r.actions("again")),
             r.actions("again")),
            ("only three entries in total", len(r.entries()) == 3, len(r.entries())), flat(r)]


@scenario("spanish", "Signal in Spanish",
          {"XAUUSD": [(0, 3945), (10, 3951), (50, 3927), (60, 3927)]},
          [(2, "post", "sig", "ORO VENTA 3950\nStop: 3962\nObjetivo 1: 3940\nObjetivo 2: 3928")])
def _(r):
    return [("read as a gold SELL", r.entries() and all(x["side"] == "SELL" and x["symbol"] == "XAUUSD" for x in r.entries())),
            ("take profits 3940 and 3928", sorted({x["price"] for x in r.exits("take profit")}) == [3928.0, 3940.0]), flat(r)]


@scenario("sentence", "Signal written as a sentence",
          {"XAUUSD": [(0, 3945), (10, 3951), (50, 3929), (60, 3929)]},
          [(2, "post", "sig", "Sell Gold at 3950, stop 3961, targets 3940 and 3930")])
def _(r):
    return [("entered as a gold SELL", r.entries() and all(x["side"] == "SELL" for x in r.entries())),
            ("take profits 3940 and 3930", sorted({x["price"] for x in r.exits("take profit")}) == [3930.0, 3940.0]),
            within_risk(r, 3961), flat(r)]


@scenario("no-tp", "Signal without a take profit",
          {"XAUUSD": [(0, 3945), (10, 3951), (60, 3915), (70, 3915)]},
          [(2, "post", "sig", "SELL GOLD 3950\nSL 3960")])
def _(r):
    return [("entered", r.outcome("sig") == "ENTERED", r.outcome("sig")),
            ("left by a take profit the bot set itself", r.exits() and all(x["how"] == "take profit" for x in r.exits()),
             [(x["how"], x["price"]) for x in r.exits()]), flat(r)]


# ═════════════════════════════════════════════════════════════════════════════

def build(scenarios):
    """Messages, the price feed and each scenario's ids / time window."""
    messages, layout, next_id = [], {}, 50000
    points = {s: [] for s in SPECS}
    for index, sc in enumerate(scenarios):
        slot = START + timedelta(minutes=index * SLOT_MINUTES)
        ids = {}
        for step in sc["steps"]:
            minute, kind, label = step[0], step[1], step[2]
            next_id += 1
            ids[label] = next_id
            base = {"id": next_id, "date": (slot + timedelta(minutes=minute)).isoformat()}
            if kind == "post":
                messages.append({**base, "text": step[3]})
            elif kind == "reply":
                messages.append({**base, "text": step[4], "reply_to": ids[step[3]]})
            elif kind == "edit":
                messages.append({**base, "event": "edit", "target": ids[step[3]], "text": step[4]})
            elif kind == "delete":
                messages.append({**base, "event": "delete", "target": ids[step[3]], "text": ""})
        layout[sc["key"]] = (ids, (slot.isoformat(), (slot + timedelta(minutes=SLOT_MINUTES)).isoformat()))
        for symbol, path in sc["prices"].items():
            points[symbol] += [(slot + timedelta(minutes=m), price) for m, price in path]
    end = START + timedelta(minutes=len(scenarios) * SLOT_MINUTES)
    feed = {}
    for symbol, pts in points.items():
        if not pts:
            pts = [(START, {"XAUUSD": 3945, "XAGUSD": 48.5, "EURUSD": 1.085, "GBPUSD": 1.27, "BTCUSD": 98500,
                            "US30": 44200}[symbol])]
        digits, wick = SPECS[symbol]["digits"], SPECS[symbol]["spread"]
        bars, t, i = [], START, 0
        price = pts[0][1]
        while t < end:
            while i + 1 < len(pts) and pts[i + 1][0] <= t:
                i += 1
            if i + 1 < len(pts) and pts[i][0] <= t and pts[i + 1][0] - pts[i][0] <= timedelta(minutes=SLOT_MINUTES):
                (t0, p0), (t1, p1) = pts[i], pts[i + 1]
                span = (t1 - t0).total_seconds()
                a = p0 + (p1 - p0) * (t - t0).total_seconds() / span
                b = p0 + (p1 - p0) * min((t + timedelta(minutes=1) - t0).total_seconds(), span) / span
            else:                                   # between scenarios: stand still at the next slot's start
                a = b = pts[i][1] if pts[i][0] <= t else price
            price = b
            bars.append([t.isoformat(), round(a, digits), round(max(a, b) + wick / 3, digits),
                         round(min(a, b) - wick / 3, digits), round(b, digits)])
            t += timedelta(minutes=1)
        feed[symbol] = {"spec": SPECS[symbol], "bars": bars}
    return messages, feed, layout, end


def replay(messages, feed, end, workdir: Path, run: int, runner: bool):
    """One run of the worker; this process plays the bot side and serves the price feed."""
    db = workdir / f"replay-{run}.db"
    for stale in workdir.glob(f"replay-{run}.db*"):
        stale.unlink()
    env = {**os.environ, "DATABASE_URL": f"file:{db}", "SIM_BRIDGE_PORT": str(5600 + run)}
    subprocess.run([sys.executable, "-m", "prisma", "db", "push", "--schema", "prisma/schema.prisma", "--skip-generate"],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (workdir / "messages.json").write_text(json.dumps(messages, ensure_ascii=False))
    settings = {
        "channel_id": CHANNEL_ID, "channel_name": CHANNEL_NAME,
        "settings": {"max_risk_per_trade_percent": 1.0, "enable_runner_split": runner, "runner_share_percent": 50.0,
                     "enable_instant_execution": True, "min_lot_size": 0.01, "max_open_positions": 50,
                     "enable_breakeven_move": False, "enable_trailing_stop": False, "enable_auto_partial": False,
                     "enable_auto_take_profit": True, "max_total_risk_per_symbol_percent": 0.0},
        "overrides": {},
    }
    (workdir / "settings.json").write_text(json.dumps(settings))
    proc = subprocess.Popen(
        [sys.executable, "-m", "simulator.flow_replay_worker", "--messages", str(workdir / "messages.json"),
         "--settings", str(workdir / "settings.json"), "--until", end.isoformat(),
         "--log", str(workdir / f"worker-{run}.log")],
        cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    events = []
    with open(workdir / f"events-{run}.jsonl", "w") as out:
        for line in proc.stdout:
            if not line.startswith("@@FLOW "):
                continue
            event = json.loads(line[7:])
            if event["type"] == "need_symbol":
                answer = feed.get(event["symbol"], {"spec": None, "bars": []})
                proc.stdin.write(json.dumps({"symbol": event["symbol"], **answer}) + "\n")
                proc.stdin.flush()
                continue
            events.append(event)
            out.write(json.dumps(event, ensure_ascii=False) + "\n")
            if event["type"] == "message" and event["index"] % 10 == 0:
                print(f"   run {run}: message {event['index']} / {event['total']}", flush=True)
            if event["type"] in ("summary", "error"):
                break
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--runner", action="store_true")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--out")
    args = parser.parse_args()

    chosen = [s for s in SCENARIOS if not args.only
              or any(o.lower() in s["key"].lower() or o.lower() in s["title"].lower() for o in args.only)]
    messages, feed, layout, end = build(chosen)
    workdir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="flow_scenarios_"))
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "feed.json").write_text(json.dumps(feed))
    signals = sum(1 for s in chosen for st in s["steps"] if st[1] == "post" and st[2] in ("sig", "now", "sell", "buy"))
    print(f"{len(chosen)} scenarios, {len(messages)} channel events, {signals} signals; runner "
          f"{'ON' if args.runner else 'OFF'}; {args.runs} run(s); files in {workdir}", flush=True)

    runs = []
    for run in range(1, args.runs + 1):
        events = replay(messages, feed, end, workdir, run, args.runner)
        error = next((e for e in events if e["type"] == "error"), None)
        if error:
            print(f"run {run} failed: {error['error']}\n{error.get('trace', '')}")
            return 2
        runs.append({sc["key"]: Result(sc, events, *layout[sc["key"]]) for sc in chosen})

    failed_total = 0
    for run_no, results in enumerate(runs, 1):
        print(f"\n════ run {run_no} " + "═" * 66)
        passed_scenarios = 0
        for sc in chosen:
            r = results[sc["key"]]
            try:
                checks = [(c[0], bool(c[1]), c[2] if len(c) > 2 else "") for c in sc["check"](r)]
            except Exception as e:
                checks = [("check ran", False, f"{type(e).__name__}: {e}")]
            bad = [c for c in checks if not c[1]]
            passed_scenarios += not bad
            failed_total += bool(bad)
            print(f"{'PASS' if not bad else 'FAIL'}  {sc['title']}  ({len(checks) - len(bad)}/{len(checks)})  "
                  f"P/L {r.pnl():+.2f}")
            for name, _, detail in bad:
                print(f"        ✗ {name}{('  — ' + str(detail)) if detail not in ('', None) else ''}")
            flagged = [f"{label}: {text}" for label, e in r.msg.items() for text in e["review"]]
            for line in flagged:
                print(f"        ⚑ flagged for review — {line[:170]}")
        total = round(sum(r.pnl() for r in results.values()), 2)
        print(f"\nrun {run_no}: {passed_scenarios} of {len(chosen)} scenarios passed; simulated P/L {total:+.2f}")

    if len(runs) > 1:
        print("\n════ do the runs agree? " + "═" * 56)
        differing = 0
        for sc in chosen:
            signatures = [results[sc["key"]].signature() for results in runs]
            if any(sig != signatures[0] for sig in signatures[1:]):
                differing += 1
                print(f"DIFFERS  {sc['title']}")
                for part in ("outcomes", "entries", "exits", "pnl"):
                    values = [sig[part] for sig in signatures]
                    if any(v != values[0] for v in values[1:]):
                        for n, v in enumerate(values, 1):
                            print(f"        run {n} {part}: {v}")
        print(f"{len(chosen) - differing} of {len(chosen)} scenarios came out identical in every run "
              f"(same outcomes, fills, exits and P/L)")
    return 1 if failed_total else 0


if __name__ == "__main__":
    sys.exit(main())
