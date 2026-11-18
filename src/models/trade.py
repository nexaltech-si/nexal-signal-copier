"""
Trade Result Model
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class TradeResult:
    """Result of a trade execution"""
    success: bool
    position_id: Optional[str] = None
    order_id: Optional[str] = None
    entry_price: Optional[float] = None
    error_message: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    broker_response: Optional[Dict[str, Any]] = None
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            "success": self.success,
            "position_id": self.position_id,
            "order_id": self.order_id,
            "entry_price": self.entry_price,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
            "broker_response": self.broker_response
        }


@dataclass
class RiskAssessment:
    """Risk assessment result"""
    approved: bool
    calculated_lot_size: float
    risk_percent: float
    risk_amount: float
    stop_loss_pips: float
    take_profit_pips: float
    risk_reward_ratio: float
    warnings: list = field(default_factory=list)
    reason: Optional[str] = None
    # True when the ONLY reason the trade was not approved is that the risk
    # percent exceeds the configured maximum. Everything else (SL, lot size,
    # risk amount) is valid, so the trade can be offered to the user as a
    # high-risk override instead of being auto-rejected.
    risk_limit_exceeded: bool = False
    # True when the lot size was computed from a hardcoded pip-value GUESS because the broker's
    # symbol data was unavailable. The trade can then be sent for manual approval (see
    # REQUIRE_APPROVAL_FOR_ESTIMATED_SIZING) instead of being sized blindly.
    sizing_estimated: bool = False

    def to_dict(self):
        """Convert to dictionary"""
        return {
            "approved": self.approved,
            "calculated_lot_size": self.calculated_lot_size,
            "risk_percent": self.risk_percent,
            "risk_amount": self.risk_amount,
            "stop_loss_pips": self.stop_loss_pips,
            "take_profit_pips": self.take_profit_pips,
            "risk_reward_ratio": self.risk_reward_ratio,
            "warnings": self.warnings,
            "reason": self.reason,
            "risk_limit_exceeded": self.risk_limit_exceeded,
            "sizing_estimated": self.sizing_estimated,
        }
