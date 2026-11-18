"""
Magic Number Service
Manages magic number generation and mapping for order tracking
"""
from typing import Optional, List, Dict
from loguru import logger


class MagicNumberService:
    """
    Service for managing magic numbers used to track orders in MetaAPI
    
    Magic numbers are used to:
    - Link Telegram message IDs to MetaAPI orders
    - Track multiple orders from the same message (multi-TP)
    - Enable fast order lookups by message ID
    """
    
    def __init__(self):
        # Map message_id → list of magic numbers (for multi-TP)
        self.message_to_magic: Dict[int, List[int]] = {}
        
        # Map magic number → order/position IDs
        self.magic_to_orders: Dict[int, Dict[str, any]] = {}
        
        logger.info("✅ Magic number service initialized")
    
    def generate_magic_number(self, message_id: int, tp_level: int = 0) -> int:
        """
        Generate a magic number from message ID
        
        NOTE: All TPs for the same message share the SAME magic number.
        This simplifies querying MetaAPI - one query returns all related positions.
        Individual positions are distinguished by their positionId.
        
        Args:
            message_id: Telegram message ID
            tp_level: Deprecated - kept for backward compatibility, not used
            
        Returns:
            Magic number (positive integer for MT4/MT5 compatibility)
        """
        # For message IDs, take modulo to fit in reasonable range
        # Keep it under 2^31 (2147483647) for MT4/MT5 compatibility
        base_magic = abs(message_id) % 100000000  # 8 digits max
        
        # Use the base magic directly - NO tp_level suffix
        # This allows all TPs to share the same magic number
        magic = base_magic
        
        # Ensure it's positive and within range
        magic = abs(magic) % 2147483647
        
        # Store mapping (one magic per message)
        if message_id not in self.message_to_magic:
            self.message_to_magic[message_id] = []
        
        if magic not in self.message_to_magic[message_id]:
            self.message_to_magic[message_id].append(magic)
        
        logger.debug(f"🔢 Generated magic number: {magic} (message={message_id})")
        
        return magic
    
    def get_magic_numbers_for_message(self, message_id: int) -> List[int]:
        """
        Get all magic numbers associated with a message ID
        
        Args:
            message_id: Telegram message ID
            
        Returns:
            List of magic numbers
        """
        return self.message_to_magic.get(message_id, [])
    
    def register_order(
        self,
        magic_number: int,
        position_id: Optional[str] = None,
        order_id: Optional[str] = None,
        symbol: Optional[str] = None
    ):
        """
        Register an order with its magic number
        
        Args:
            magic_number: The magic number used
            position_id: MetaAPI position ID
            order_id: MetaAPI order ID
            symbol: Trading symbol
        """
        if magic_number not in self.magic_to_orders:
            self.magic_to_orders[magic_number] = {
                "position_ids": [],
                "order_ids": [],
                "symbol": symbol
            }
        
        if position_id and position_id not in self.magic_to_orders[magic_number]["position_ids"]:
            self.magic_to_orders[magic_number]["position_ids"].append(position_id)
        
        if order_id and order_id not in self.magic_to_orders[magic_number]["order_ids"]:
            self.magic_to_orders[magic_number]["order_ids"].append(order_id)
        
        logger.debug(f"📝 Registered order: magic={magic_number}, position={position_id}, order={order_id}")
    
    def get_orders_for_magic(self, magic_number: int) -> Optional[Dict]:
        """
        Get order information for a magic number
        
        Args:
            magic_number: The magic number
            
        Returns:
            Dictionary with position_ids, order_ids, symbol
        """
        return self.magic_to_orders.get(magic_number)
    
    def get_all_orders_for_message(self, message_id: int) -> List[Dict]:
        """
        Get all orders associated with a message ID
        
        Args:
            message_id: Telegram message ID
            
        Returns:
            List of order dictionaries
        """
        magic_numbers = self.get_magic_numbers_for_message(message_id)
        
        orders = []
        for magic in magic_numbers:
            order_info = self.get_orders_for_magic(magic)
            if order_info:
                order_info['magic_number'] = magic
                orders.append(order_info)
        
        return orders


# Singleton instance
magic_number_service = MagicNumberService()
