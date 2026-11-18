"""
Abstract base class for trading providers.
Defines the unified interface that both MetaAPI SDK and MT5 REST API must implement.
"""
import asyncio
import math
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List, Any

from src.models import TradingSignal, TradeResult, AccountInfo, RiskAssessment


class BaseTradingProvider(ABC):
    """
    Abstract trading provider interface.
    
    All trading backends (MetaAPI Cloud SDK, self-hosted MT5 REST API, etc.)
    must implement this interface so the rest of the system can switch
    between them transparently via the TRADING_PROVIDER config setting.
    
    Attributes:
        is_connected (bool): Whether the provider is connected and ready.
            Set by initialize() / disconnect(). Defaults to False.
    """

    is_connected: bool = False
    # False when the last positions/orders read returned [] because the read FAILED (not because the
    # account is flat). Sync logic must not infer closures/cancellations from such a snapshot.
    positions_ok: bool = True
    orders_ok: bool = True

    @staticmethod
    def _pair_legs_to_tps(legs: list, tps: list) -> tuple:
        """
        Build the per-order plan for a multi-entry (scale-in) signal.

        Pairing policy:
          • equal counts  → pair by index: leg1→TP1, leg2→TP2 (one order per leg)
          • unequal counts → cross product: every leg carries every TP, so no leg
            or target is silently dropped.

        Returns four parallel lists: (order_leg_prices, order_tps, leg_indices,
        tp_indices), all 1-based indices for recording/labeling.
        """
        n_l, n_t = len(legs), len(tps)
        order_legs, order_tps, leg_idx, tp_idx = [], [], [], []
        if n_l == n_t:
            for i in range(n_l):
                order_legs.append(legs[i])
                order_tps.append(tps[i])
                leg_idx.append(i + 1)
                tp_idx.append(i + 1)
        else:
            for li, leg in enumerate(legs, 1):
                for ti, tp in enumerate(tps, 1):
                    order_legs.append(leg)
                    order_tps.append(tp)
                    leg_idx.append(li)
                    tp_idx.append(ti)
        return order_legs, order_tps, leg_idx, tp_idx

    @staticmethod
    def instant_market_entry(
        is_buy: bool,
        current_price: Optional[float],
        entries: list,
        max_deviation: float,
        stop_loss: Optional[float] = None,
        take_profits: Optional[list] = None,
    ) -> Optional[float]:
        """
        For an instant ("NOW") signal: the entry level to fill at market although price
        has already moved past it on the worse side, or None to keep normal placement.

        Normal placement (every signal): a level the live price has reached or bettered
        fills at market; a level not reached yet waits as a LIMIT. "NOW" means the trader
        wants in immediately, so when NO level has been reached the nearest one is filled
        at market — only while price is within max_deviation of it (never chase a run-away
        move), still on the right side of the stop loss, and short of the first target.
        Further levels stay limits. If a level is already reached, "now" is satisfied.
        """
        levels = [float(e) for e in entries if e is not None]
        if not levels or current_price is None or not max_deviation or max_deviation <= 0:
            return None
        if any((current_price <= e) if is_buy else (current_price >= e) for e in levels):
            return None
        nearest = max(levels) if is_buy else min(levels)
        if abs(current_price - nearest) > max_deviation + 1e-9:
            return None
        if stop_loss and ((current_price <= stop_loss) if is_buy else (current_price >= stop_loss)):
            return None
        tps = [float(t) for t in (take_profits or []) if t]
        if tps:
            first_tp = min(tps) if is_buy else max(tps)
            if (current_price >= first_tp) if is_buy else (current_price <= first_tp):
                return None
        return nearest

    @staticmethod
    def instant_one_leg_entry(
        is_buy: bool,
        current_price: Optional[float],
        entries: list,
        stop_loss: Optional[float],
        take_profits: Optional[list],
        max_tp1_progress_pct: float,
    ) -> Optional[float]:
        """
        For an instant ("NOW") signal that price has run past by MORE than the
        deviation cap: the level at which ONE order still fills at market, or None
        to keep every order a limit.

        Without it a fast signal was missed entirely (2026-10-20, #34792: "SELL NOW
        @ 4132" arrived with price at 4129, 30 pips past a 20-pip cap — both orders
        waited as limits that never filled while the provider ran +90 pips). One
        order goes in only while price has covered less than max_tp1_progress_pct of
        the way from the level to the first target — chasing a move that is mostly
        done buys a few points of reward for the full risk — and is still on the
        right side of the stop loss. 0 turns it off.
        """
        levels = [float(e) for e in entries if e is not None]
        if not levels or current_price is None or not max_tp1_progress_pct or max_tp1_progress_pct <= 0:
            return None
        if any((current_price <= e) if is_buy else (current_price >= e) for e in levels):
            return None  # a level is reached: normal placement fills it already
        if stop_loss and ((current_price <= stop_loss) if is_buy else (current_price >= stop_loss)):
            return None
        tps = [float(t) for t in (take_profits or []) if t]
        if not tps:
            return None  # no target to measure the move against: don't chase
        nearest = max(levels) if is_buy else min(levels)
        first_tp = min(tps) if is_buy else max(tps)
        span = (first_tp - nearest) if is_buy else (nearest - first_tp)
        if span <= 0:
            return None
        moved = (current_price - nearest) if is_buy else (nearest - current_price)
        return nearest if moved / span < max_tp1_progress_pct / 100 else None

    @staticmethod
    def same_risk_volume(
        volume: float, planned_entry: float, fill_price: float,
        stop_loss: Optional[float], step: float, volume_min: float,
    ) -> float:
        """Lots for a fill at fill_price that risk no more than `volume` did from
        planned_entry to the stop loss — rounded DOWN to the step, never below the
        broker minimum. A fill closer to the SL keeps the volume (never sized up)."""
        if not stop_loss:
            return volume
        planned, actual = abs(planned_entry - stop_loss), abs(fill_price - stop_loss)
        if planned <= 0 or actual <= planned:
            return volume
        step = step or 0.01
        scaled = round(math.floor(volume * planned / actual / step + 1e-9) * step, 8)
        return max(volume_min or step, scaled)

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize connection to the trading backend.
        Should handle retries and raise on unrecoverable failure.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the trading backend."""
        ...

    # ── Account ──────────────────────────────────────────────────────────

    @abstractmethod
    async def get_account_info(self, use_cache: bool = True) -> AccountInfo:
        """
        Return current account information (balance, equity, margin, etc.).
        Implementations should cache aggressively to avoid rate limits.
        """
        ...

    # ── Symbol resolution ────────────────────────────────────────────────

    @abstractmethod
    async def resolve_symbol(self, symbol: str) -> str:
        """
        Resolve a canonical symbol name (e.g. 'XAUUSD') to the broker-
        specific name (e.g. 'XAUUSDm', 'GOLD+').
        """
        ...

    @property
    def live_reads(self) -> bool:
        """True if positions/orders/account reads are live (pushed), so caching is unnecessary."""
        return False

    async def wait_for_change(self, timeout: float) -> bool:
        """
        Wait up to `timeout` seconds for a pushed position/order change.
        Default (polling providers): just sleep. Returns True if woken by a change.
        """
        await asyncio.sleep(timeout)
        return False

    async def get_positions_by_symbol(self, symbol: str) -> List[dict]:
        """Open positions whose symbol matches `symbol` (broker suffixes tolerated)."""
        want = (symbol or "").upper()
        if not want:
            return []
        positions = await self.get_open_positions(use_cache=True)
        out = []
        for p in positions:
            sym = str(p.get("symbol", "")).upper()
            if sym and (sym.startswith(want) or want.startswith(sym)):
                out.append(p)
        return out

    async def get_symbols_snapshot(self, select_unquoted: bool = True) -> List[dict]:
        """
        Every broker symbol with its current quote, as a list of dicts with at
        least: name, bid, ask (and optionally digits, description, visible).

        Optional capability — backends that can't dump quotes in bulk return an
        empty list, and callers (e.g. the symbol matcher) fall back to pricing a
        shortlist symbol by symbol.
        """
        return []

    @abstractmethod
    async def get_symbol_price(self, symbol: str) -> dict:
        """
        Return current price data for a symbol.

        The returned dict MUST contain at least:
            bid, ask
        And optionally:
            profitTickValue, lossTickValue, spread
        """
        ...

    @abstractmethod
    async def get_symbol_specification(self, symbol: str) -> dict:
        """
        Return symbol specification dict with keys like:
        tickSize, contractSize, digits, volumeStep, volumeMin, volumeMax
        """
        ...

    @abstractmethod
    async def round_lot_size(self, symbol: str, lot_size: float) -> float:
        """Round a lot size to the broker's volume step for the symbol."""
        ...

    # ── Trade execution ──────────────────────────────────────────────────

    @abstractmethod
    async def execute_trade(
        self,
        signal: TradingSignal,
        risk_assessment: RiskAssessment,
        magic_number: Optional[int] = None,
    ) -> TradeResult:
        """
        Execute a trade based on signal and risk assessment.
        Handles market, limit, stop, and multi-TP orders.
        """
        ...

    # ── Positions ────────────────────────────────────────────────────────

    @abstractmethod
    async def get_open_positions(self, use_cache: bool = True) -> List[dict]:
        """
        Return all open positions as a list of dicts.
        
        Each dict MUST contain at least:
            id, symbol, type ('POSITION_TYPE_BUY' | 'POSITION_TYPE_SELL'),
            volume, openPrice, currentPrice, stopLoss, takeProfit, magic,
            profit, comment
        """
        ...

    @abstractmethod
    async def get_positions_by_magic(
        self, magic_number: int, use_cache: bool = True
    ) -> List[dict]:
        """Return open positions filtered by magic number."""
        ...

    @abstractmethod
    async def close_position(
        self, position_id: str, volume: Optional[float] = None
    ) -> Any:
        """
        Close a position (full or partial).
        If volume is given, perform a partial close.
        """
        ...

    @abstractmethod
    async def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Any:
        """Modify the SL and/or TP of an open position."""
        ...

    async def remove_take_profit(self, ticket: str, stop_loss: Optional[float],
                                 pending: bool = False, price: Optional[float] = None) -> Any:
        """
        Remove the TP of a position (or a pending order, with its price), keeping
        its SL — used for the runner part of a signal. MT5 convention: TP 0 = none.
        """
        if pending:
            return await self.modify_order(ticket, stop_loss=stop_loss, take_profit=0.0, price=price)
        return await self.modify_position(ticket, stop_loss=stop_loss, take_profit=0.0)

    async def fetch_mirror_snapshot(self) -> dict:
        """
        Strict, uncached read of the live account for the EA trade copier
        (src/api/ea_mirror_router.py): {"account": {...}, "positions": [...],
        "orders": [...]}, all in this provider's normalized dict shapes.

        Unlike get_open_positions()/get_all_pending_orders(), which fall back to
        a cache or an empty list on error, this MUST raise whenever it cannot
        vouch for the result — the copier reads "position missing from the
        snapshot" as "master closed it" and closes the mirror's copy.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support the EA mirror snapshot")

    # ── Pending orders ───────────────────────────────────────────────────

    @abstractmethod
    async def get_all_pending_orders(self, use_cache: bool = True) -> List[dict]:
        """
        Return all pending orders as a list of dicts.
        
        Each dict MUST contain at least:
            id, symbol, type, volume, openPrice, stopLoss, takeProfit, magic
        """
        ...

    @abstractmethod
    async def get_orders_by_magic(self, magic_number: int) -> List[dict]:
        """Return pending orders filtered by magic number."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> Any:
        """Cancel a pending order by its ID."""
        ...

    # ── Combined queries ─────────────────────────────────────────────────

    @abstractmethod
    async def get_all_trades_by_magic(
        self, magic_number: int, use_cache: bool = True
    ) -> dict:
        """
        Return both positions and orders matching a magic number.
        
        Returns:
            {"positions": [...], "orders": [...], "total_count": int}
        """
        ...

    # ── Market Data ───────────────────────────────────────────────────────

    @abstractmethod
    async def get_historical_candles(
        self,
        symbol: str,
        timeframe: str = '1h',
        start_time: Optional[datetime] = None,
        limit: int = 100
    ) -> Optional[List[dict]]:
        """
        Fetch historical OHLC candle data for market analysis.

        Args:
            symbol: Trading symbol (will be resolved internally)
            timeframe: Timeframe for candles (e.g., '1h', '15m', '1d')
            start_time: Start time for historical data (defaults to 100 hours ago)
            limit: Maximum number of candles to fetch

        Returns:
            List of candle dicts with keys: time, open, high, low, close, volume
            Returns None if data is unavailable
        """
        ...

    # ── History ──────────────────────────────────────────────────────────

    @abstractmethod
    async def get_deals_by_position(
        self,
        position_id: str,
        symbol: Optional[str] = None,
        from_date: Optional[str] = None,
    ) -> List[dict]:
        """
        Get closed deal history for a specific position.
        Used for profit calculation on closed/partially closed trades.
        
        Args:
            position_id: MT5 position ticket
            symbol: Trading symbol to filter by (prevents position-ID reuse contamination)
            from_date: ISO date string start of search window (default: 30 days ago)
        """
        ...

    # ── Trade lifecycle (optional – MT5 REST only) ────────────────────────

    async def get_trade_status(self, ticket: str) -> Optional[dict]:
        """
        Return the definitive lifecycle status for a single ticket.

        Returns a dict with at least:
            status  : "PENDING" | "RUNNING" | "CLOSED_PROFIT" | "CLOSED_LOSS"
                      | "CLOSED_BREAKEVEN" | "CANCELED" | "EXPIRED"
                      | "REJECTED" | "UNKNOWN"
            is_open : bool
            total_profit : float  (for closed statuses)

        Returns None if the provider does not support this endpoint
        (e.g. MetaAPI).  Callers must handle None gracefully.
        """
        return None

    async def get_batch_trade_status(self, tickets: List[str]) -> Optional[List[dict]]:
        """
        Return lifecycle status for multiple tickets in a single call.

        Returns a list of dicts (same shape as get_trade_status) keyed by
        'ticket', or None if the provider does not support batch queries.
        """
        return None
