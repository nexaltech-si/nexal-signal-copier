"""
Trading Signal Model
Unified model compatible with AI processors and main app
"""
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime
from .enums import SignalAction, OrderType, SignalStatus, SignalType


@dataclass
class TradingSignal:
    """
    Unified trading signal model
    Compatible with both advanced AI processors and main app
    """
    # Core signal data
    symbol: Optional[str] = None
    action: Optional[SignalAction] = None
    order_type: Optional[OrderType] = None
    
    # Price levels
    entry_price: Optional[float] = None
    entry_range_min: Optional[float] = None  # For range orders (e.g., "buy 3840-3850")
    entry_range_max: Optional[float] = None  # For range orders
    # Discrete scale-in legs (e.g. "SELL NOW @ 4081 / MORE SELL @ 4091").
    # Each value is a separate simultaneous entry at its own price, SAME direction,
    # sharing this signal's SL + TPs. Distinct from entry_range (a single zone) and
    # from a plan (conditional/if-stopped-out re-entry). None or <2 items = single entry.
    entries: Optional[List[float]] = None
    stop_loss: Optional[float] = None
    take_profit: List[float] = field(default_factory=list)
    
    # Position management
    lot_size: Optional[float] = None
    percentage_close: Optional[float] = None
    
    # Metadata
    signal_id: Optional[str] = None
    raw_message: Optional[str] = None
    confidence: float = 0.0
    # Verbatim text the extraction AI returned (before JSON parsing) — stored so the
    # exact model output can be inspected in the dashboard. None for pattern-matched signals.
    ai_raw_response: Optional[str] = None
    
    # Telegram source
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    message_id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Status tracking
    status: SignalStatus = SignalStatus.RECEIVED
    
    # Instant execution flag (for market orders triggered by keywords like "now")
    instant_execution: bool = False
    # Entry intent read by the extraction AI: "market" (enter now) / "pending" (wait
    # for the level) / None (unknown — keyword detection decides).
    entry_mode: Optional[str] = None
    # SL was not in the message: an instant entry got a temporary SL that the
    # follow-up message is expected to replace (see signal_continuity).
    temp_stop_loss: bool = False
    # Max money at risk for this order set (one risk budget per signal). None = the
    # normal per-trade risk %. Set for temporary-SL entries and continuation top-ups.
    risk_budget_amount: Optional[float] = None
    # Continuation of an existing signal (follow-up / repost / edit): the parent
    # Signal id and the magic number its orders share, so replies reach every order.
    continuation_of: Optional[str] = None
    # Top-up of a running setup: (lots already on TPs, lots already without TP), so
    # the runner share is measured over the whole setup, not only the added orders.
    runner_setup: Optional[tuple] = None
    magic_override: Optional[int] = None

    # Raw image bytes from the Telegram message (not persisted to dict, saved separately)
    image_data: Optional[bytes] = None

    # Plan signal fields — set when signal is a conditional multi-entry plan
    is_plan: bool = False
    plan_data: Optional[dict] = None  # {primary: {...}, fallback: {...}}

    # Set when vision extraction has a usable direction/entry/target but couldn't
    # pin down one field (currently only "symbol") — holds the signal for user
    # input instead of dropping it. See signal_clarification_service.
    needs_clarification: Optional[str] = None

    # Route to the manual approval queue even when the channel auto-executes.
    # Set when extraction had reason to doubt the message was a fresh setup
    # (status caption, "no entry / waiting confirmation", vision-only from a
    # non-trading caption). A real field so dataclasses.replace() keeps it.
    force_manual_approval: bool = False

    # Placed by hand from the dashboard's Telegram page: the owner reviewed it, so
    # the automatic flow's judgement (message age, continuity, brain, approval
    # queue) is skipped; account protection and risk sizing still apply.
    manual_placement: bool = False

    # Legacy compatibility
    signal_type: Optional[SignalType] = None
    take_profit_levels: List[float] = field(default_factory=list)
    
    def discrete_entry_prices(self) -> Optional[List[float]]:
        """
        Return the list of scale-in entry legs (>=2 distinct prices) for a
        multi-entry signal, or None for a normal single-entry signal.

        Execution decides market-vs-limit for each leg against the live price,
        so only the raw leg prices are stored here — not the order kind.
        """
        if not self.entries:
            return None
        legs = [float(e) for e in self.entries if e is not None]
        # De-duplicate while preserving order (a repeated price is not a real leg)
        seen: set = set()
        unique = [p for p in legs if not (p in seen or seen.add(p))]
        return unique if len(unique) >= 2 else None

    def __post_init__(self):
        """Ensure backwards compatibility and smart signal_type detection"""
        # Multi-entry: keep entry_price populated with the primary (first) leg so
        # all single-entry code paths (sizing, display, fallback) keep working.
        if self.entries:
            legs = [float(e) for e in self.entries if e is not None]
            if legs and self.entry_price is None:
                self.entry_price = legs[0]

        # Sync take_profit and take_profit_levels
        if self.take_profit and not self.take_profit_levels:
            self.take_profit_levels = self.take_profit
        elif self.take_profit_levels and not self.take_profit:
            self.take_profit = self.take_profit_levels
            
        # Map signal_type to action/order_type for legacy support
        if self.signal_type and not self.action:
            if self.signal_type in [SignalType.BUY, SignalType.BUY_LIMIT, SignalType.BUY_STOP]:
                self.action = SignalAction.OPEN
                self.order_type = OrderType.BUY
            elif self.signal_type in [SignalType.SELL, SignalType.SELL_LIMIT, SignalType.SELL_STOP]:
                self.action = SignalAction.OPEN
                self.order_type = OrderType.SELL
            elif self.signal_type == SignalType.CLOSE:
                self.action = SignalAction.CLOSE
        
        # SMART SIGNAL_TYPE DETECTION: Set signal_type to LIMIT when entry_price is specified
        # This ensures signals like "Buy at 170" are correctly identified as limit orders
        if not self.signal_type and self.action == SignalAction.OPEN and self.entry_price:
            if self.order_type == OrderType.BUY:
                self.signal_type = SignalType.BUY_LIMIT
            elif self.order_type == OrderType.SELL:
                self.signal_type = SignalType.SELL_LIMIT
        
        # If still no signal_type, default to market order types
        if not self.signal_type and self.action == SignalAction.OPEN:
            if self.order_type == OrderType.BUY:
                self.signal_type = SignalType.BUY
            elif self.order_type == OrderType.SELL:
                self.signal_type = SignalType.SELL
    
    def to_dict(self):
        """Convert to dictionary for database storage"""
        return {
            "symbol": self.symbol,
            "action": self.action.value if self.action else None,
            "order_type": self.order_type.value if self.order_type else None,
            "entry_price": self.entry_price,
            "entry_range_min": self.entry_range_min,
            "entry_range_max": self.entry_range_max,
            "entries": self.entries,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "lot_size": self.lot_size,
            "percentage_close": self.percentage_close,
            "signal_id": self.signal_id,
            "raw_message": self.raw_message,
            "confidence": self.confidence,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "status": self.status.value,
            "signal_type": self.signal_type.value if self.signal_type else None,
            "instant_execution": self.instant_execution
        }
