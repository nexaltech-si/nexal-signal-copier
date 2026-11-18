"""
Reply replay — run historical replies through the LIVE ReplyHandlerService.

For every signal the simulator extracts, a SimBook keeps the legs the live bot
would have placed (one position per entry × TP). M1 candles from the MT5 bridge
(read-only) advance those legs in time: pending orders fill when price touches
their entry, open positions close on SL/TP. When a reply arrives, the book's
state at that minute is handed to the real ReplyHandlerService — real reply AI,
real executors — through injected fakes:

  SimBroker     records close / partial / SL / TP / cancel and applies it to the book
  SimDB         answers the handler's lookups from the book; every write is dropped
  NullForwarder no Telegram posts
  brain=None    no TradingBrain calls

Nothing reaches the account, the database or Telegram.
"""
from __future__ import annotations

import bisect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.models import TradingSignal, SignalAction, OrderType


def _utc(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _contract_size(symbol: str) -> float:
    s = (symbol or '').upper()
    if 'XAU' in s or 'GOLD' in s:
        return 100.0
    if 'XAG' in s or 'SILVER' in s:
        return 5000.0
    if any(k in s for k in ('BTC', 'ETH', 'US30', 'NAS', 'SPX', 'GER', 'OIL', 'WTI')):
        return 1.0
    return 100000.0


class SimBook:
    """Legs per signal message id, advanced through M1 candles."""

    MAX_TPS = 3

    def __init__(self, provider, window_start: datetime, now: Optional[datetime] = None):
        self.provider = provider
        self.window_start = _utc(window_start)
        self._now = _utc(now)  # tests pin the clock; live runs use the real time
        self.signals: Dict[int, Dict[str, Any]] = {}
        self._bars: Dict[str, Tuple[List[datetime], List[tuple]]] = {}

    # ── prices ────────────────────────────────────────────────────────────────
    async def _ensure_bars(self, symbol: str) -> None:
        if symbol in self._bars:
            return
        times: List[datetime] = []
        rows: List[tuple] = []
        try:
            minutes = int(((self._now or datetime.now(timezone.utc)) - self.window_start).total_seconds() // 60) + 180
            # MT5 bridge serves at most 10 000 bars per request (~7 trading days of M1)
            candles = await self.provider.get_historical_candles(symbol, '1m', limit=max(500, min(minutes, 10_000)))
            for c in candles or []:
                t = _utc(c.get('time'))
                if t is not None:
                    times.append(t)
                    rows.append((float(c['open']), float(c['high']), float(c['low']), float(c['close'])))
            order = sorted(range(len(times)), key=times.__getitem__)
            times = [times[i] for i in order]
            rows = [rows[i] for i in order]
            times = self._to_utc(symbol, times, self._now)
            logger.info(f"SimBook: {len(times)} M1 bars for {symbol}"
                        + (f" ({times[0]:%m-%d %H:%M} → {times[-1]:%m-%d %H:%M})" if times else ""))
        except Exception as e:
            logger.warning(f"SimBook: no candles for {symbol} ({e}) — replies on it replay without prices")
        self._bars[symbol] = (times, rows)

    @staticmethod
    def _to_utc(symbol: str, times: List[datetime], now: Optional[datetime] = None) -> List[datetime]:
        """
        MT5 stamps bars in broker SERVER time (often UTC+2/+3), not UTC. While the
        market is open the newest M1 bar is within a few minutes of "now" in server
        time, so its gap to UTC rounds to the broker's whole-hour offset.
        """
        if not times:
            return times
        now = now or datetime.now(timezone.utc)
        gap_h = (times[-1] - now).total_seconds() / 3600
        offset = round(gap_h)
        if abs(gap_h - offset) <= 0.25 and abs(offset) <= 14:
            if offset:
                logger.info(f"SimBook: {symbol} bars are in server time UTC{offset:+d} — shifting to UTC")
            return [t - timedelta(hours=offset) for t in times]
        logger.warning(f"SimBook: can't detect server-time offset for {symbol} (market closed?) — assuming UTC")
        return times

    def price_at(self, symbol: str, ts: datetime) -> Optional[float]:
        times, rows = self._bars.get(symbol, ([], []))
        i = bisect.bisect_right(times, _utc(ts)) - 1
        return rows[i][3] if i >= 0 else None

    # ── signals → legs ────────────────────────────────────────────────────────
    async def register(self, message_id: int, signal: TradingSignal, ts: datetime) -> int:
        if signal.action != SignalAction.OPEN or not signal.symbol or signal.is_plan:
            return 0
        if getattr(signal, 'force_manual_approval', False):
            return 0  # live queues it for approval — no position unless a human approves
        ts = _utc(ts)
        await self._ensure_bars(signal.symbol)
        px = self.price_at(signal.symbol, ts)
        is_buy = signal.order_type == OrderType.BUY
        tps = list(signal.take_profit or [])[: self.MAX_TPS] or [None]
        # Same placement rule as MT5RestProvider (single and multi-order paths):
        # a leg goes MARKET when the live price is at/better than its entry
        # (BUY: price <= entry, SELL: price >= entry), otherwise a LIMIT at the entry.
        # An instant ("NOW") signal with no leg reached also fills its nearest leg at
        # market within the deviation cap (BaseTradingProvider.instant_market_entry).
        pairs = []  # (entry level or None for market, tp)
        legs_px = signal.discrete_entry_prices() if hasattr(signal, 'discrete_entry_prices') else None
        if legs_px:
            from src.integrations.trading.base_provider import BaseTradingProvider
            order_legs, order_tps, _, _ = BaseTradingProvider._pair_legs_to_tps(list(legs_px), tps)
            pairs = list(zip(order_legs, order_tps))  # live leg→TP pairing
        elif signal.entry_range_min and signal.entry_range_max:
            lo, hi = sorted((signal.entry_range_min, signal.entry_range_max))
            n = len(tps)
            levels = [hi - (hi - lo) * i / max(n - 1, 1) for i in range(n)] if is_buy else \
                     [lo + (hi - lo) * i / max(n - 1, 1) for i in range(n)]
            pairs = list(zip(levels, tps))
        else:
            pairs = [(signal.entry_price, tp) for tp in tps]
        if px is None and any(e is None for e, _ in pairs):
            return 0
        from src.integrations.trading.base_provider import BaseTradingProvider
        from src.models.enums import SignalType
        chase = one_leg = None
        if (getattr(signal, 'instant_execution', False) and px is not None
                and signal.signal_type not in (SignalType.BUY_STOP, SignalType.SELL_STOP)
                and all(e is not None for e, _ in pairs)):
            from src.services.execution_policy import instant_max_deviation_price
            chase = BaseTradingProvider.instant_market_entry(
                is_buy, px, [e for e, _ in pairs], instant_max_deviation_price(signal.symbol),
                signal.stop_loss, [t for t in tps if t is not None],
            )
            # Beyond the cap, live still fills ONE order — the furthest TP at the nearest
            # level — with lots scaled to the same risk (BaseTradingProvider.instant_one_leg_entry).
            if chase is None:
                from config import settings
                level = BaseTradingProvider.instant_one_leg_entry(
                    is_buy, px, [e for e, _ in pairs], signal.stop_loss,
                    [t for t in tps if t is not None],
                    float(getattr(settings, 'instant_one_leg_max_tp1_progress', 0) or 0),
                )
                at_level = [i for i, (e, t) in enumerate(pairs) if level is not None and abs(e - level) < 1e-9 and t is not None]
                if at_level:
                    one_leg = (max if is_buy else min)(at_level, key=lambda i: float(pairs[i][1]))
        legs = []
        for i, (entry, tp) in enumerate(pairs):
            market = (entry is None or px is None or ((px <= entry) if is_buy else (px >= entry))
                      or (chase is not None and abs(entry - chase) < 1e-9))
            volume = 0.12
            if i == one_leg:
                market = True
                volume = BaseTradingProvider.same_risk_volume(volume, entry, px, signal.stop_loss, 0.01, 0.01)
            legs.append({
                'id': f"{message_id}-{i}", 'symbol': signal.symbol, 'buy': is_buy,
                'entry': float(px if market and px is not None else entry), 'kind': 'market' if market else 'limit',
                'status': 'open' if market else 'pending',
                'sl': signal.stop_loss, 'tp': tp, 'volume': volume,
                'created': ts, 'opened': ts if market else None, 'checked': ts,
                'close_reason': None,
            })
        self.signals[message_id] = {'symbol': signal.symbol, 'buy': is_buy, 'legs': legs, 'ts': ts}
        return len(legs)

    def advance(self, message_id: int, ts: datetime) -> None:
        sig = self.signals.get(message_id)
        if not sig:
            return
        times, rows = self._bars.get(sig['symbol'], ([], []))
        ts = _utc(ts)
        for leg in sig['legs']:
            if leg['status'] not in ('pending', 'open'):
                continue
            lo = bisect.bisect_right(times, leg['checked'])
            hi = bisect.bisect_right(times, ts)
            for i in range(lo, hi):
                _o, h, l, _c = rows[i]
                if leg['status'] == 'pending':
                    e, buy = leg['entry'], leg['buy']
                    hit = (l <= e) if (buy and leg['kind'] == 'limit') or (not buy and leg['kind'] == 'stop') else (h >= e)
                    if hit:
                        leg['status'], leg['opened'] = 'open', times[i]
                    continue  # SL/TP checked from the next bar
                sl, tp, buy = leg['sl'], leg['tp'], leg['buy']
                if sl and ((buy and l <= sl) or (not buy and h >= sl)):
                    leg.update(status='closed', close_reason='SL hit')
                    break
                if tp and ((buy and h >= tp) or (not buy and l <= tp)):
                    leg.update(status='closed', close_reason='TP hit')
                    break
            leg['checked'] = max(leg['checked'], ts)

    def state(self, message_id: int, ts: datetime) -> Tuple[List[dict], List[dict], Optional[float]]:
        sig = self.signals.get(message_id)
        if not sig:
            return [], [], None
        self.advance(message_id, ts)
        cur = self.price_at(sig['symbol'], ts)
        cs = _contract_size(sig['symbol'])
        positions, orders = [], []
        for leg in sig['legs']:
            side = 'BUY' if leg['buy'] else 'SELL'
            if leg['status'] == 'open':
                now = cur if cur is not None else leg['entry']
                pnl = (now - leg['entry']) * (1 if leg['buy'] else -1) * cs * leg['volume']
                positions.append({
                    'id': leg['id'], 'symbol': leg['symbol'], 'type': f'POSITION_TYPE_{side}',
                    'openPrice': leg['entry'], 'currentPrice': now, 'stopLoss': leg['sl'],
                    'takeProfit': leg['tp'], 'profit': round(pnl, 2), 'volume': leg['volume'],
                    'openTime': leg['opened'].isoformat(),
                })
            elif leg['status'] == 'pending':
                orders.append({
                    'id': leg['id'], 'symbol': leg['symbol'], 'type': f"ORDER_TYPE_{side}_{leg['kind'].upper()}",
                    'openPrice': leg['entry'], 'currentPrice': cur, 'stopLoss': leg['sl'],
                    'takeProfit': leg['tp'], 'volume': leg['volume'],
                    'openTime': leg['created'].isoformat(), 'time': leg['created'].isoformat(),
                })
        return positions, orders, cur

    def latest_active(self, ts: datetime, text: str = "") -> Optional[int]:
        """
        Message id of the newest signal with open/pending legs at `ts` — the target
        of a standalone (non-reply) command, like MessageHandler._latest_active_signal
        (which prefers a signal whose symbol the text names).
        """
        ts = _utc(ts)
        candidates = []
        for mid, sig in self.signals.items():
            if sig['ts'] > ts:
                continue
            self.advance(mid, ts)
            if any(l['status'] in ('open', 'pending') for l in sig['legs']):
                candidates.append((sig['ts'], mid, sig['symbol']))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        lowered = (text or '').upper()
        for _, mid, sym in candidates:
            if sym and (sym in lowered or (sym.startswith('XAU') and 'GOLD' in lowered)):
                return mid
        return candidates[0][1]

    def leg(self, leg_id: str) -> Optional[dict]:
        for sig in self.signals.values():
            for leg in sig['legs']:
                if leg['id'] == leg_id:
                    return leg
        return None

    def summary(self, message_id: int, ts: datetime) -> str:
        positions, orders, cur = self.state(message_id, ts)
        sig = self.signals.get(message_id)
        if not sig:
            return "no tracked signal"
        closed = [l['close_reason'] for l in sig['legs'] if l['status'] == 'closed']
        pnl = sum(p['profit'] for p in positions)
        parts = [f"{len(positions)} open (P/L {pnl:+.0f})", f"{len(orders)} pending"]
        if closed:
            parts.append(f"{len(closed)} closed ({', '.join(sorted(set(closed)))})")
        if any(l['status'] == 'cancelled' for l in sig['legs']):
            parts.append(f"{sum(l['status'] == 'cancelled' for l in sig['legs'])} cancelled")
        return f"{sig['symbol']} @ {cur}: " + ", ".join(parts)


class SimBroker:
    """Broker stand-in for one reply: serves the book's state, applies the handler's actions."""

    def __init__(self, book: SimBook, message_id: int, ts: datetime):
        self.book, self.mid, self.ts = book, message_id, _utc(ts)
        self.calls: List[str] = []

    async def get_all_trades_by_magic(self, magic):
        positions, orders, _ = self.book.state(self.mid, self.ts)
        return {'positions': positions, 'orders': orders}

    async def close_position(self, position_id, volume=None, **kw):
        leg = self.book.leg(position_id)
        if leg and leg['status'] == 'open':
            if volume and volume < leg['volume'] - 1e-9:
                leg['volume'] = round(leg['volume'] - volume, 2)
                self.calls.append(f"partial {position_id} {volume}")
            else:
                leg.update(status='closed', close_reason='closed by reply')
                self.calls.append(f"close {position_id}")
        return {'success': True}

    async def modify_position(self, position_id, stop_loss=None, take_profit=None, **kw):
        leg = self.book.leg(position_id)
        if leg:
            if stop_loss is not None and stop_loss != leg['sl']:
                tag = 'BE' if abs(stop_loss - leg['entry']) <= max(abs(leg['entry']) * 0.0003, 1e-9) else 'SL'
                self.calls.append(f"{tag} {position_id} → {stop_loss}")
                leg['sl'] = stop_loss
            if take_profit is not None and take_profit != leg['tp']:
                self.calls.append(f"TP {position_id} → {take_profit}")
                leg['tp'] = take_profit
        return {'success': True}

    async def modify_order(self, order_id, stop_loss=None, take_profit=None, price=None, **kw):
        leg = self.book.leg(order_id)
        if leg and stop_loss is not None:
            leg['sl'] = stop_loss
            self.calls.append(f"SL order {order_id} → {stop_loss}")
        return {'success': True}

    async def cancel_order(self, order_id, **kw):
        leg = self.book.leg(order_id)
        if leg and leg['status'] == 'pending':
            leg.update(status='cancelled', close_reason='cancelled by reply')
            self.calls.append(f"cancel {order_id}")
        return {'success': True}

    async def execute_trade(self, signal=None, risk_assessment=None, magic_number=None, **kw):
        from src.models.trade import TradeResult
        self.calls.append(f"OPEN add-position {getattr(signal, 'symbol', '')} {getattr(signal, 'lot_size', '')}")
        return TradeResult(success=True, position_id='sim-add', error_message=None)

    async def get_symbol_specification(self, symbol):
        return {'volumeStep': 0.01, 'volumeMin': 0.01}

    async def round_lot_size(self, symbol, volume):
        return round(volume, 2)


class _Model:
    def __init__(self, book: SimBook):
        self.book = book

    def __getattr__(self, name):
        async def f(*a, where=None, **kw):
            if name == 'find_first' and where and 'messageId' in where:
                sig = self.book.signals.get(where['messageId'])
                if sig:
                    return SimpleNamespace(id=f"sim-{where['messageId']}", symbol=sig['symbol'], channelName='simulator')
                return None
            return [] if name == 'find_many' else None
        return f


class SimDB:
    """Read answers from the book; every write is a no-op."""

    def __init__(self, book: SimBook):
        self.book = book
        self.db = SimpleNamespace(signal=_Model(book), signalreply=_Model(book), messagemapping=_Model(book),
                                  trade=_Model(book), tradeaction=_Model(book))

    async def get_trades_by_magic_number(self, magic):
        from src.services.magic_number_service import magic_number_service
        for mid, sig in self.book.signals.items():
            if magic_number_service.generate_magic_number(mid) == magic:
                return [{'id': f"t-{l['id']}", 'signalId': f"sim-{mid}", 'symbol': l['symbol'],
                         'positionId': l['id'] if l['status'] != 'pending' else None,
                         'orderId': l['id'] if l['status'] == 'pending' else None,
                         'status': {'pending': 'PENDING', 'open': 'EXECUTED'}.get(l['status'], 'CLOSED'),
                         'entryPrice': l['entry'], 'magicNumber': magic} for l in sig['legs']]
        return []

    async def get_signal_by_id(self, signal_id):
        mid = int(str(signal_id).replace('sim-', '') or 0)
        sig = self.book.signals.get(mid)
        if not sig:
            return None
        leg = sig['legs'][0]
        return {'id': signal_id, 'symbol': sig['symbol'], 'entryPrice': leg['entry'],
                'stopLoss': leg['sl'], 'takeProfit': str([l['tp'] for l in sig['legs']])}

    async def create_signal_reply(self, **kw):
        return None

    def __getattr__(self, name):
        async def f(*a, **kw):
            return None
        return f


class NullForwarder:
    def __getattr__(self, name):
        async def f(*a, **kw):
            return None
        return f


class _IdentitySpread:
    async def adjust_sl_for_position(self, position_id, sl):
        return sl


class _SimContext:
    """Symbol resolution from the replied-to signal; no live DB/conversation state."""

    def __init__(self, real, symbol: Optional[str]):
        self.real, self.symbol = real, symbol

    def _extract_symbol_from_message(self, text):
        try:
            return self.real._extract_symbol_from_message(text)
        except Exception:
            return None

    async def resolve_symbol_for_command(self, **kw):
        return self.symbol

    def add_to_conversation_history(self, *a, **kw):
        pass


class _RecordingAI:
    """Pass-through to the real TradeCommandProcessor that remembers its decision."""

    def __init__(self, real):
        self.real, self.decision = real, None

    async def process_command(self, *a, **kw):
        cmd = await self.real.process_command(*a, **kw)
        self.decision = cmd
        return cmd

    def __getattr__(self, name):
        return getattr(self.real, name)


async def replay_reply(book: SimBook, command_processor, context_manager, *, reply_to: int,
                       text: str, ts: datetime, channel_id: str, image_data=None) -> Dict[str, Any]:
    """Run one reply through the live ReplyHandlerService against the book."""
    from src.services.reply_handler_service import ReplyHandlerService

    sig = book.signals.get(reply_to)
    state_before = book.summary(reply_to, ts) if sig else "reply is not to a tracked signal"
    broker = SimBroker(book, reply_to, ts)
    ai = _RecordingAI(command_processor)
    handler = ReplyHandlerService(
        trading_provider=broker, db=SimDB(book), forwarder=NullForwarder(), brain=None,
        spread_adjustment=_IdentitySpread(), ai_processor=ai,
        context_manager=_SimContext(context_manager, sig['symbol'] if sig else None),
    )
    result = await handler.handle_reply(
        reply_to_message_id=reply_to, chat_id=channel_id, command=text,
        reply_message_id=None, command_timestamp=_utc(ts), image_data=image_data,
    )
    d = ai.decision
    return {
        'state_before': state_before,
        'ai_action': d.action if d else None,
        'ai_value': getattr(d, 'value', None) if d else None,
        'ai_percentage': getattr(d, 'percentage', None) if d else None,
        'broker_calls': broker.calls,
        'result': result or {},
        'state_after': book.summary(reply_to, ts) if sig else None,
    }
