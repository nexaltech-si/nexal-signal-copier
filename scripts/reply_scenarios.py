"""
End-to-end reply scenario matrix — run INSIDE the bot container (needs the DB for API keys):

    docker cp scripts/reply_scenarios.py telegram-trading-bot:/app/scripts/
    docker exec -w /app telegram-trading-bot python3 scripts/reply_scenarios.py              # 220 standard
    docker exec -e SET=human -w /app telegram-trading-bot python3 scripts/reply_scenarios.py # 175 human-style

Each provider message is run against 5 account states (only pending, open in profit,
open in loss, part-filled, nothing open) and the broker calls are checked.

Real: ReplyHandlerService.handle_reply + real reply AI (keys from the settings DB).
Fake: broker, database writes, Telegram forwarder, trading brain — nothing reaches
the live account, the DB tables or Telegram.
"""
import asyncio, os, sys, json, logging
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

logging.disable(logging.CRITICAL)
from loguru import logger
logger.remove()

import src.models  # noqa
from config.settings import settings

T0 = datetime.now(timezone.utc) - timedelta(hours=1)
CMD_TS = datetime.now(timezone.utc)

# ── account states (XAUUSD SELL signal, entries 4120/4130, SL 4140, TP 4100/4080) ──
def pos(pid, entry, now, profit):
    return {'id': pid, 'symbol': 'XAUUSD', 'type': 'POSITION_TYPE_SELL', 'openPrice': entry,
            'currentPrice': now, 'stopLoss': 4140.0, 'takeProfit': 4100.0, 'profit': profit,
            'volume': 0.12, 'openTime': T0.isoformat()}
def order(oid, entry, now):
    return {'id': oid, 'symbol': 'XAUUSD', 'type': 'ORDER_TYPE_SELL_LIMIT', 'openPrice': entry,
            'currentPrice': now, 'stopLoss': 4140.0, 'takeProfit': 4100.0, 'volume': 0.12,
            'openTime': T0.isoformat(), 'time': T0.isoformat()}

STATES = {
    'PENDING':     ([], [order('o1', 4120.0, 4106.0), order('o2', 4130.0, 4106.0)]),
    'OPEN_PROFIT': ([pos('p1', 4120.0, 4106.0, 168.0), pos('p2', 4130.0, 4106.0, 288.0)], []),
    'OPEN_LOSS':   ([pos('p1', 4120.0, 4131.0, -132.0), pos('p2', 4130.0, 4131.0, -12.0)], []),
    'PART_FILLED': ([pos('p1', 4120.0, 4106.0, 168.0)], [order('o2', 4130.0, 4106.0)]),
    'NOTHING':     ([], []),
}
STATE_MSGID = {s: 50000 + i for i, s in enumerate(STATES)}

# ── fake broker: records every write ─────────────────────────────────────────
class FakeBroker:
    def __init__(self, positions, orders):
        self.positions, self.orders, self.calls = positions, orders, []
    async def get_all_trades_by_magic(self, magic):
        return {'positions': [dict(p) for p in self.positions], 'orders': [dict(o) for o in self.orders]}
    async def close_position(self, pid, volume=None, **kw):
        self.calls.append(('partial' if volume else 'close', pid)); return {'success': True}
    async def modify_position(self, pid, stop_loss=None, take_profit=None, **kw):
        p = next(p for p in self.positions if p['id'] == pid)
        if stop_loss is not None and stop_loss != p['stopLoss']:
            self.calls.append(('be' if abs(stop_loss - p['openPrice']) < 1.0 else 'sl', pid))
        if take_profit is not None and take_profit != p['takeProfit']:
            self.calls.append(('tp', pid))
        return {'success': True}
    async def modify_order(self, oid, stop_loss=None, take_profit=None, price=None, **kw):
        self.calls.append(('sl', oid)); return {'success': True}
    async def cancel_order(self, oid, **kw):
        self.calls.append(('cancel', oid)); return {'success': True}
    async def execute_trade(self, *a, **kw):
        self.calls.append(('open', None)); return {'success': True}
    async def get_symbol_specification(self, s): return {'volumeStep': 0.01, 'volumeMin': 0.01}
    async def round_lot_size(self, s, v): return round(v, 2)

# ── fake db_service: reads return state-consistent data, writes are no-ops ───
class _Model:
    def __init__(self, **ret): self.ret = ret
    def __getattr__(self, name):
        async def f(*a, **kw):
            if name == 'find_first' and 'where' in kw and 'messageId' in kw['where']:
                mid = kw['where']['messageId']
                return SimpleNamespace(id=f'sig-{mid}', symbol='XAUUSD', channelName='TEST')
            return [] if name.startswith('find_many') else None
        return f
class FakeDB:
    def __init__(self):
        self.db = SimpleNamespace(signal=_Model(), signalreply=_Model(), messagemapping=_Model(),
                                  trade=_Model(), tradeaction=_Model())
    async def get_trades_by_magic_number(self, magic):
        from src.services.magic_number_service import magic_number_service as m
        for st, mid in STATE_MSGID.items():
            if m.generate_magic_number(mid) == magic:
                ps, os_ = STATES[st]
                return ([{'id': f't-{p["id"]}', 'signalId': f'sig-{mid}', 'positionId': p['id'], 'status': 'EXECUTED',
                          'symbol': 'XAUUSD', 'magicNumber': magic} for p in ps] +
                        [{'id': f't-{o["id"]}', 'signalId': f'sig-{mid}', 'orderId': o['id'], 'status': 'PENDING',
                          'symbol': 'XAUUSD', 'magicNumber': magic} for o in os_])
        return []
    async def get_signal_by_id(self, sid):
        return {'id': sid, 'symbol': 'XAUUSD', 'entryPrice': 4120.0, 'stopLoss': 4140.0, 'takeProfit': '[4100, 4080]'}
    async def create_signal_reply(self, **kw): return 'reply-test'
    def __getattr__(self, name):
        async def f(*a, **kw): return None
        return f

class FakeCtx:
    def _extract_symbol_from_message(self, t): return 'XAUUSD' if any(k in t.lower() for k in ('xau', 'gold')) else None
    async def resolve_symbol_for_command(self, **kw): return 'XAUUSD'
    def add_to_conversation_history(self, **kw): pass

# ── scenarios: message -> {state: check(effects) } ───────────────────────────
NONE = {()}
def E(*xs): return tuple(sorted(set(xs)))
ANY_CANCEL_OR_NONE = {E('cancel'), ()}

S = []
def sc(msg, P, OP, OL, PF, note=''):
    S.append((msg, {'PENDING': P, 'OPEN_PROFIT': OP, 'OPEN_LOSS': OL, 'PART_FILLED': PF, 'NOTHING': NONE}, note))

# progress reports
sc("Running!👈🏻",                          {E('cancel'), ()}, NONE, NONE, {E('cancel'), ()})
sc("80 pips",                                {E('cancel')}, NONE, NONE, {E('cancel'), ()})
sc("120 pip",                                {E('cancel')}, NONE, NONE, {E('cancel'), ()})
sc("Near TP",                                {E('cancel')}, NONE, NONE, {E('cancel'), ()})
sc("+250 pips running 🔥🔥",                  {E('cancel')}, NONE, NONE, {E('cancel'), ()})
sc("TP1 hit ✅ +100 pips",                    {E('cancel')}, {(), E('be')}, NONE, {E('cancel'), (), E('be'), E('be', 'cancel')})
sc("TP2 done ✅ trade closed",                {E('cancel'), ()}, {(), E('close')}, {(), E('close')}, {E('cancel'), (), E('close', 'cancel'), E('close')})
# instructions
sc("• XAU +140 pips running now - Set B.E  \n\n~ Save some profits!",
   {E('cancel')}, {E('partial', 'be'), E('partial'), E('be')}, {E('partial'), E('be'), E('partial', 'be'), ()},
   {E('partial', 'be'), E('partial', 'be', 'cancel'), E('be', 'cancel'), E('partial', 'cancel'), E('be')})
sc("Set BE",                                 {E('cancel')}, {E('be')}, {E('be'), ()}, {E('be'), E('be', 'cancel')})
sc("B.E now ✅",                              {E('cancel')}, {E('be')}, {E('be'), ()}, {E('be'), E('be', 'cancel')})
sc("Risk free now ✅",                        {E('cancel')}, {E('be')}, {E('be'), ()}, {E('be'), E('be', 'cancel')})
sc("close now",                              {E('cancel')}, {E('close')}, {E('close')}, {E('close', 'cancel')})
sc("close all now market is reversing",      {E('cancel')}, {E('close')}, {E('close')}, {E('close', 'cancel')})
sc("close half",                             {E('cancel')}, {E('partial')}, {E('partial')}, {E('partial'), E('partial', 'cancel')})
sc("cloze half",                             {E('cancel')}, {E('partial')}, {E('partial')}, {E('partial'), E('partial', 'cancel')}, 'typo')
sc("Take partials and set BE",               {E('cancel')}, {E('partial', 'be')}, {E('partial', 'be'), E('partial')}, {E('partial', 'be'), E('partial', 'be', 'cancel')})
sc("secure profits now",                     {E('cancel')}, {E('close'), E('partial')}, {E('close'), E('partial'), ()}, {E('close', 'cancel'), E('partial'), E('partial', 'cancel'), E('close')})
sc("move SL to 4135",                        {E('sl')}, {E('sl')}, {E('sl')}, {E('sl')}, 'all positions AND pending orders get the new SL')
sc("lock 20 pips profit",                    {E('cancel'), ()}, {E('sl')}, {(), E('sl')}, {E('sl'), E('sl', 'cancel')})
sc("new TP 4090",                            NONE, {E('tp')}, {E('tp')}, {E('tp')})
sc("Cancel pending orders",                  {E('cancel')}, NONE, NONE, {E('cancel')})
sc("Invalid, don't enter",                   {E('cancel')}, {(), E('close')}, {(), E('close')}, {E('cancel'), E('close', 'cancel')})
sc("SL hit",                                 {E('cancel'), ()}, {E('close'), ()}, {E('close'), ()}, {E('close', 'cancel'), E('cancel'), E('close'), ()})
sc("Close 4120 hold 4130",                   {E('cancel'), ()}, {E('close')}, {E('close')}, {E('close')}, 'must close ONLY the 4120 leg')
sc("Close worst entry",                      {E('cancel'), ()}, {E('close')}, {E('close')}, {E('close'), E('close', 'cancel')}, 'must close ONLY 1')
sc("Target 1: HIT ✅\n• Pips: +100 💰\n• Action: SL to Entry 🔒", {E('cancel')}, {E('be')}, {E('be'), ()}, {E('be'), E('be', 'cancel')})
sc("Action: Market Exit 🛡",                  {E('cancel')}, {E('close')}, {E('close')}, {E('close', 'cancel')})
# brag / marketing / chat — must not touch open positions
sc("XAUUSD Target-Smacked +150 Pips Running, Deal Done - Profit Secured 🎯 THANKS GOLD!",
   {E('cancel'), ()}, {(), E('close')}, NONE, {E('cancel'), (), E('close', 'cancel'), E('close')}, 'provider finished — close is defensible')
sc("Once a Trader, Always a Trader! ✨ XAU bleeding +200 pips running! Timely booked maximum profits. TRADE LIKE A PRO.",
   {E('cancel'), ()}, NONE, NONE, {E('cancel'), ()}, 'brag post that closed 2 positions before')
sc("Give me likes on this signal ☝🏻☝🏻",       NONE, NONE, NONE, NONE)
sc("Join VIP for 10 signals daily, DM me 💎",   NONE, NONE, NONE, NONE)
sc("I take entry in GOLD from 4395 when i was typing it move up in second\n\nWhat about you ??", NONE, NONE, NONE, NONE)
sc("GOLD will move up waiting pullback to execute our trades!😊", NONE, NONE, NONE, NONE)
sc("If candle closes above 4135 close it",   NONE, NONE, NONE, NONE, 'conditional — no action yet')
sc("Hold, don't close yet",                  NONE, NONE, NONE, NONE)
sc("We are in drawdown, stay calm and hold", NONE, NONE, NONE, NONE)
sc("🔥🔥🔥",                                   NONE, NONE, NONE, NONE)
sc("Close 50% and move SL to entry",         {E('cancel')}, {E('partial', 'be')}, {E('partial', 'be'), E('partial')}, {E('partial', 'be'), E('partial', 'be', 'cancel')})
sc("TP3 hit 🎯 full target, trade closed",    {E('cancel'), ()}, {(), E('close')}, {(), E('close')}, {E('cancel'), (), E('close', 'cancel'), E('close')})
sc("Price is near entry, be careful",        NONE, NONE, NONE, NONE)
sc("Cancel the 4130 order, keep the rest",   {E('cancel')}, {(), E('close')}, {(), E('close')}, {E('cancel')}, 'only the 4130 leg may be touched')
sc("Close first entry only",                 {E('cancel'), ()}, {E('close')}, {E('close')}, {E('close')}, 'must close ONLY p1')
sc("Move stop to 4110 lock profits",          {E('sl'), E('cancel')}, {E('sl')}, {E('sl'), ()}, {E('sl', 'cancel')})
sc("Re-enter sell 4125 SL 4145 TP 4100",     {(), E('cancel')}, NONE, NONE, {(), E('cancel')}, 're-entry is handled by the new-signal path')


# ── HUMAN-STYLE set: typos, cut-off text, slang, caps, rambling, other languages ──
if os.environ.get('SET') == 'human':
    S.clear()
    CL = {E('close')}; CLC = {E('close', 'cancel')}; CA = {E('cancel')}
    PA = {E('partial')}; PAC = {E('partial'), E('partial', 'cancel')}
    BE = {E('be')}; BEC = {E('be'), E('be', 'cancel')}
    PBE = {E('partial', 'be'), E('partial')}; PBEC = {E('partial', 'be'), E('partial', 'be', 'cancel'), E('partial'), E('partial', 'cancel')}
    # typos
    sc("clse half guys",                  CA, PA, PA, PAC, 'typo')
    sc("cls 50% now",                     CA, PA, PA, PAC, 'abbrev')
    sc("close hlf n set b e",             CA, PBE, PBE, PBEC, 'typos + spaced b e')
    sc("set be pls",                      CA, BE, BE | {()}, BEC)
    sc("sl to entri now",                 CA, BE, BE | {()}, BEC, 'typo')
    sc("mve sl entry",                    CA, BE, BE | {()}, BEC, 'typo')
    sc("exit noww!!",                     CA, CL, CL, CLC)
    sc("CLOSE ALL NOW!!!",                CA, CL, CL, CLC, 'caps')
    sc("get out fast",                    CA, CL, CL, CLC)
    sc("cansel pending limit",            CA, NONE, NONE, CA, 'typo')
    sc("tp1 hittt 🔥🔥",                   CA, NONE | BE, NONE, CA | NONE | BEC, 'typo')
    sc("80pips",                          CA, NONE, NONE, CA | NONE, 'no space')
    sc("neer tp",                         CA, NONE, NONE, CA | NONE, 'typo')
    sc("secure sum profit",               CA, CL | PA, CL | PA | NONE, CLC | PAC | CL, 'typo')
    # cut-off / unfinished
    sc("+140 pips running now - Set B",   CA | NONE, BE | NONE | PBE, BE | NONE, BEC | CA | NONE, 'cut off mid-word')
    sc("close ha",                        CA | NONE, PA | CL | NONE, PA | CL | NONE, PAC | CLC | CL | NONE, 'cut off')
    sc("move sl to",                      CA | NONE, BE | NONE, BE | NONE, BEC | CA | NONE, 'no price')
    sc("guys i think",                    NONE, NONE, NONE, NONE, 'unfinished thought')
    # slang / rambling / questions
    sc("guys i think we should take some profit here market looks tired, close half and let rest run",
       CA, PA, PA, PAC, 'rambling instruction')
    sc("gold 120 pip run 🔥 secure some",  CA, PA | CL, PA | CL | NONE, PAC | CLC | CL, 'slang')
    sc("should we close?",                NONE, NONE, NONE, NONE, 'question, not an order')
    sc("close? no way, hold 💪",           NONE, NONE, NONE, NONE, 'negated')
    sc("dont exit yet hold tight",        NONE, NONE, NONE, NONE, 'negated typo')
    sc("4110",                            NONE | CA, NONE, NONE, NONE | CA, 'bare number')
    sc("sl 4135",                         {E('sl')}, {E('sl')}, {E('sl')}, {E('sl')}, 'terse SL')
    sc("tp 4090",                         NONE, {E('tp')}, {E('tp')}, {E('tp')}, 'terse TP')
    sc("BE",                              CA, BE, BE | NONE, BEC, 'single token')
    sc("half",                            CA | NONE, PA | NONE, PA | NONE, PAC | NONE, 'single word')
    sc("ok",                              NONE, NONE, NONE, NONE)
    sc("👍",                              NONE, NONE, NONE, NONE)
    # Roman Urdu / Hindi, Arabic
    sc("half close kar do aur sl entry pe rakh do", CA, PBE, PBE, PBEC, 'roman urdu: close half + SL to entry')
    sc("profit book karlo bhai",          CA, CL | PA, CL | PA | NONE, CLC | PAC | CL, 'roman urdu: book profit')
    sc("abhi hold karo, close mat karna", NONE, NONE, NONE, NONE, 'roman urdu: hold, do not close')
    sc("اغلق الصفقة الآن",                 CA, CL, CL, CLC, 'arabic: close the trade now')
    sc("ثبت الوقف على الدخول",             CA, BE, BE | NONE, BEC, 'arabic: SL to entry')

# ── runner ────────────────────────────────────────────────────────────────────
async def main():
    from src.core.prisma_client import prisma_client
    from src.services.settings_service import get_settings_service
    await prisma_client.initialize()
    svc = await get_settings_service(prisma_client.client, encryption_key=os.getenv("SETTINGS_ENCRYPTION_KEY"))
    settings.set_db_settings_service(svc); await settings.reload_from_db()

    import src.services.reply_handler_service as rhs
    rhs.db_service = FakeDB()
    rhs.spread_adjustment_service = SimpleNamespace(adjust_sl_for_position=lambda pid, sl: _ret(sl))
    import src.services.signal_forwarder_service as sfs
    async def _noop(*a, **kw): return None
    sfs.signal_forwarder_service.reply_breakeven = _noop
    from ai.trading_brain import trading_brain
    trading_brain.handle_reply = _noop  # no Hermes calls
    from ai.trade_command_processor import TradeCommandProcessor
    ai = TradeCommandProcessor(settings)

    sem = asyncio.Semaphore(6)
    async def run(msg, state, allowed, note):
        async with sem:
            ps, os_ = STATES[state]
            h = rhs.ReplyHandlerService.__new__(rhs.ReplyHandlerService)
            h.trading_provider = FakeBroker([dict(p) for p in ps], [dict(o) for o in os_])
            h.ai_processor, h.context_manager = ai, FakeCtx()
            try:
                res = await h.handle_reply(reply_to_message_id=STATE_MSGID[state], chat_id='-100TEST',
                                           command=msg, reply_message_id=None, command_timestamp=CMD_TS)
                err = None
            except Exception as e:
                res, err = {}, repr(e)
            eff = E(*[c[0] for c in h.trading_provider.calls]) if h.trading_provider.calls else ()
            ok = eff in allowed and not err
            # leg/count-specific checks
            if ok and msg.startswith("Close 4120") and state in ('OPEN_PROFIT', 'OPEN_LOSS', 'PART_FILLED'):
                ok = h.trading_provider.calls == [('close', 'p1')]
            if ok and msg == "Close worst entry" and state in ('OPEN_PROFIT', 'OPEN_LOSS'):
                ok = h.trading_provider.calls == [('close', 'p1')]
            if ok and msg in ("Close first entry only",) and state in ('OPEN_PROFIT', 'OPEN_LOSS', 'PART_FILLED'):
                ok = h.trading_provider.calls == [('close', 'p1')]
            if ok and msg.startswith("Cancel the 4130") and state != 'NOTHING' and h.trading_provider.calls:
                ok = h.trading_provider.calls in ([('cancel', 'o2')], [('close', 'p2')])
            # every position (and order, for SL) must be covered — no "first one only"
            if ok:
                for kind in ('be', 'sl', 'tp', 'partial'):
                    hit = {i for k, i in h.trading_provider.calls if k == kind}
                    if hit:
                        need = {p['id'] for p in ps} | ({o['id'] for o in os_} if kind == 'sl' and (msg.startswith('move SL to 4135') or msg == 'sl 4135') else set())
                        if msg in ("Close first entry only",): continue
                        if hit != need:
                            ok = False; note = f"{kind} applied to {sorted(hit)} but should cover {sorted(need)}"
            return dict(msg=msg, state=state, ok=ok, effects=eff, calls=h.trading_provider.calls,
                        allowed=sorted(allowed), note=note, err=err,
                        result=(res.get('message') or res.get('error') or res.get('reason') or '')[:90])
    jobs = [run(m, st, allowed[st], note) for m, allowed, note in S for st in STATES]
    results = await asyncio.gather(*jobs)
    json.dump(results, open('/tmp/reply_scenarios_results.json', 'w'), default=str, ensure_ascii=False, indent=1)
    fails = [r for r in results if not r['ok']]
    print(f"TOTAL {len(results)}  PASS {len(results) - len(fails)}  FAIL {len(fails)}")
    for r in fails:
        print(f"FAIL [{r['state']}] {r['msg'][:60]!r}\n     got {r['effects'] or '(none)'} calls={r['calls']} | expected one of {r['allowed']} | {r['result']} {r['err'] or ''} {r['note']}")

async def _ret(v): return v
asyncio.run(main())
