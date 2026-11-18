"""
Trade Mapper Service
Maps Telegram messages to executed trades for tracking updates/modifications
"""
from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger

from src.models.message import MessageIdentifier


class TradeMapper:
    """
    Maps messages to trades for precise tracking
    Enables handling of trade updates, modifications, and closures
    """
    
    def __init__(self):
        # Map message keys to trade data
        self.message_to_trade: Dict[str, dict] = {}
        
        # Map position IDs to message keys (for reverse lookup)
        self.position_to_message: Dict[str, str] = {}
        
        # Track active trades by symbol
        self.symbol_trades: Dict[str, List[dict]] = {}
        
        logger.info("✅ Trade mapper initialized")
    
    def register_trade(
        self,
        message_id: MessageIdentifier,
        symbol: str,
        position_id: Optional[str] = None,
        order_id: Optional[str] = None,
        signal_data: Optional[dict] = None
    ) -> dict:
        """
        Register a new trade mapping
        
        Args:
            message_id: Telegram message identifier
            symbol: Trading symbol
            position_id: MetaAPI position ID
            order_id: MetaAPI order ID
            signal_data: Additional signal data
            
        Returns:
            Trade record dictionary
        """
        message_key = message_id.get_key()
        
        trade_record = {
            "message_id": message_id,
            "symbol": symbol,
            "position_id": position_id,
            "order_id": order_id,
            "signal_data": signal_data or {},
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "status": "EXECUTED" if position_id else "PENDING",
            "related_messages": [],
        }
        
        # Store mapping
        self.message_to_trade[message_key] = trade_record
        
        # Store position mapping for reverse lookup
        if position_id:
            self.position_to_message[position_id] = message_key
        
        # Track by symbol
        if symbol not in self.symbol_trades:
            self.symbol_trades[symbol] = []
        self.symbol_trades[symbol].append(trade_record)
        
        logger.info(f"📝 Registered trade: {symbol} | Message: {message_key} | Position: {position_id}")
        return trade_record
    
    def find_trade_by_message(self, message_id: MessageIdentifier) -> Optional[dict]:
        """Find trade by message identifier"""
        message_key = message_id.get_key()
        return self.message_to_trade.get(message_key)
    
    def find_trade_by_position(self, position_id: str) -> Optional[dict]:
        """Find trade by position ID"""
        message_key = self.position_to_message.get(position_id)
        if message_key:
            return self.message_to_trade.get(message_key)
        return None
    
    def find_recent_trade_by_symbol(self, symbol: str) -> Optional[dict]:
        """Find most recent trade for a symbol"""
        trades = self.symbol_trades.get(symbol, [])
        if not trades:
            return None
        
        # Return most recent trade
        active_trades = [t for t in trades if t["status"] in ["EXECUTED", "PENDING"]]
        if active_trades:
            return max(active_trades, key=lambda t: t["created_at"])
        
        return None
    
    def update_trade_status(self, message_key: str, status: str):
        """Update trade status"""
        if message_key in self.message_to_trade:
            self.message_to_trade[message_key]["status"] = status
            self.message_to_trade[message_key]["updated_at"] = datetime.now()
            logger.info(f"✅ Updated trade status: {message_key} -> {status}")
    
    def add_related_message(self, trade_record: dict, message_id: MessageIdentifier):
        """Add a related message to a trade (for tracking updates)"""
        if "related_messages" not in trade_record:
            trade_record["related_messages"] = []
        
        trade_record["related_messages"].append({
            "message_id": message_id.message_id,
            "timestamp": message_id.timestamp
        })
        trade_record["updated_at"] = datetime.now()
    
    def get_active_trades(self, symbol: Optional[str] = None) -> List[dict]:
        """Get all active trades, optionally filtered by symbol"""
        if symbol:
            trades = self.symbol_trades.get(symbol, [])
            return [t for t in trades if t["status"] in ["EXECUTED", "PENDING"]]
        
        # Get all active trades
        active = []
        for trades in self.symbol_trades.values():
            active.extend([t for t in trades if t["status"] in ["EXECUTED", "PENDING"]])
        return active


# Singleton instance
trade_mapper = TradeMapper()
