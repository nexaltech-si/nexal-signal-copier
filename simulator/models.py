"""
Simulator data models — SimulatedTrade and SimulationResults.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import List, Dict, Optional


@dataclass
class SimulatedTrade:
    """Single message processed through the live-system pipeline."""

    message_id: int
    timestamp: datetime
    original_message: str

    # Intent classification
    intent: Optional[str] = None            # SIGNAL / COMMAND / STATUS / NOT_TRADING
    intent_source: Optional[str] = None     # "ai" | "keyword_fallback" | "default"

    # AI extraction
    ai_extracted: bool = False
    ai_action: Optional[str] = None
    ai_order_type: Optional[str] = None      # BUY / SELL direction
    ai_symbol: Optional[str] = None
    ai_entry: Optional[float] = None
    ai_sl: Optional[float] = None
    ai_tp: Optional[List[float]] = None
    ai_confidence: Optional[float] = None
    ai_raw_response: Optional[str] = None

    # Pattern-matching extraction
    pattern_extracted: bool = False
    pattern_action: Optional[str] = None
    pattern_order_type: Optional[str] = None  # BUY / SELL direction
    pattern_symbol: Optional[str] = None
    pattern_entry: Optional[float] = None
    pattern_sl: Optional[float] = None
    pattern_tp: Optional[List[float]] = None
    pattern_raw_response: Optional[str] = None

    # Extraction routing
    extraction_method: Optional[str] = None  # ai | pattern | image_vision | fused | failed | command | prefiltered

    # Reply context
    is_reply: bool = False
    reply_to_message_id: Optional[int] = None

    # Image handling
    has_image: bool = False
    image_extracted: bool = False

    # Signal flags
    is_reenter: bool = False
    is_risky: bool = False
    is_limit_order: bool = False
    is_stop_order: bool = False
    is_breakeven: bool = False
    risk_level: Optional[str] = None
    special_instructions: Optional[List[str]] = None

    # Plan signals
    is_plan: bool = False
    plan_symbol: Optional[str] = None

    # Reply replay through the live ReplyHandlerService (simulator/reply_replay.py)
    reply_state: Optional[str] = None          # account state for the replied-to signal before the reply
    reply_ai_action: Optional[str] = None      # what the reply AI decided (None = no action)
    reply_broker_calls: List[str] = field(default_factory=list)  # simulated broker writes
    reply_result: Optional[str] = None         # handler's result message / error
    reply_state_after: Optional[str] = None

    # Command processing
    command_action: Optional[str] = None
    command_value: Optional[float] = None
    command_percentage: Optional[float] = None

    # Context resolution
    context_resolved: bool = False
    context_resolution_method: Optional[str] = None  # "ai" | "database"

    # Brain review
    brain_reviewed: bool = False
    brain_verdict: Optional[str] = None     # APPROVE | REJECT | MODIFY
    brain_reason: Optional[str] = None

    # Errors
    extraction_error: Optional[str] = None
    processing_error: Optional[str] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class SimulationResults:
    """Aggregated results of a full channel simulation run."""

    channel_id: int
    channel_name: str
    start_date: datetime
    end_date: datetime
    total_messages: int

    # Message type counts
    reply_messages: int = 0
    plain_command_count: int = 0  # commands caught by Layer 0+1 (zero AI)

    # Intent distribution
    intent_signal_count: int = 0
    intent_command_count: int = 0
    intent_status_count: int = 0
    intent_non_trading_count: int = 0
    intent_ai_classified: int = 0
    intent_keyword_fallback: int = 0

    # Extraction stats
    ai_extracted_count: int = 0
    pattern_extracted_count: int = 0
    image_extracted_count: int = 0
    fused_extracted_count: int = 0
    failed_extraction_count: int = 0
    prefiltered_count: int = 0

    # Image stats
    messages_with_images: int = 0
    images_processed: int = 0

    # Plans
    plan_signals: int = 0

    # Complex signal flags
    reenter_commands: int = 0
    risky_trades: int = 0
    limit_orders: int = 0
    stop_orders: int = 0
    breakeven_commands: int = 0

    # Command stats
    commands_processed: int = 0
    commands_close: int = 0
    commands_partial_close: int = 0
    commands_modify_sl: int = 0
    commands_modify_tp: int = 0
    commands_breakeven: int = 0
    commands_cancel: int = 0

    # Context resolution
    context_resolved_count: int = 0
    ai_context_resolved: int = 0
    db_context_resolved: int = 0

    # Brain review
    brain_reviewed_count: int = 0
    brain_approved: int = 0
    brain_rejected: int = 0
    brain_modified: int = 0

    # Action distribution (open/close/etc.)
    open_signals: int = 0
    close_signals: int = 0
    modify_signals: int = 0
    partial_close_signals: int = 0
    cancel_signals: int = 0

    # Accuracy metrics
    ai_accuracy: float = 0.0
    pattern_accuracy: float = 0.0

    # Distributions
    symbol_distribution: Dict[str, int] = field(default_factory=dict)
    common_errors: Dict[str, int] = field(default_factory=dict)

    # Per-trade details
    trades: List[SimulatedTrade] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["start_date"] = self.start_date.isoformat()
        data["end_date"] = self.end_date.isoformat()
        data["trades"] = [t.to_dict() for t in self.trades]
        return data

    def summary(self) -> dict:
        """Lightweight summary without per-trade detail (for API status polling)."""
        total_extracted = self.ai_extracted_count + self.pattern_extracted_count
        return {
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "total_messages": self.total_messages,
            "reply_messages": self.reply_messages,
            "plain_command_count": self.plain_command_count,
            "intent_signal_count": self.intent_signal_count,
            "intent_command_count": self.intent_command_count,
            "intent_status_count": self.intent_status_count,
            "intent_non_trading_count": self.intent_non_trading_count,
            "ai_extracted_count": self.ai_extracted_count,
            "pattern_extracted_count": self.pattern_extracted_count,
            "image_extracted_count": self.image_extracted_count,
            "fused_extracted_count": self.fused_extracted_count,
            "failed_extraction_count": self.failed_extraction_count,
            "prefiltered_count": self.prefiltered_count,
            "commands_processed": self.commands_processed,
            "plan_signals": self.plan_signals,
            "open_signals": self.open_signals,
            "close_signals": self.close_signals,
            "modify_signals": self.modify_signals,
            "partial_close_signals": self.partial_close_signals,
            "context_resolved_count": self.context_resolved_count,
            "brain_reviewed_count": self.brain_reviewed_count,
            "brain_approved": self.brain_approved,
            "brain_rejected": self.brain_rejected,
            "brain_modified": self.brain_modified,
            "ai_accuracy": round(self.ai_accuracy, 2),
            "pattern_accuracy": round(self.pattern_accuracy, 2),
            "total_extracted": total_extracted,
            "symbol_distribution": self.symbol_distribution,
            "common_errors": self.common_errors,
        }
