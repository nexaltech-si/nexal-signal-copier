"""
Account Information Model
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class AccountInfo:
    """Trading account information"""
    balance: float
    equity: float
    margin: float
    free_margin: float
    open_positions: int
    currency: str = "USD"
    leverage: Optional[int] = None
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            "balance": self.balance,
            "equity": self.equity,
            "margin": self.margin,
            "free_margin": self.free_margin,
            "open_positions": self.open_positions,
            "currency": self.currency,
            "leverage": self.leverage
        }
