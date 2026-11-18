"""
Spread Adjustment Service
Centralizes spread adjustment logic for SL to prevent immediate closure
"""
from loguru import logger
from config import settings
from src.integrations.trading.provider_factory import create_trading_provider


class SpreadAdjustmentService:
    """
    Service to adjust stop loss for spread
    Prevents immediate closure due to spread
    """
    
    def __init__(self):
        self._trading_provider = None  # Lazy initialization
    
    @property
    def trading_provider(self):
        """Lazy initialization of trading provider"""
        if self._trading_provider is None:
            self._trading_provider = create_trading_provider()
        return self._trading_provider
    
    async def adjust_sl_for_spread(
        self,
        symbol: str,
        stop_loss: float,
        is_buy: bool,
        apply_adjustment: bool = True
    ) -> float:
        """
        Adjust stop loss to account for spread
        
        Args:
            symbol: Trading symbol
            stop_loss: Original stop loss value
            is_buy: True for BUY orders, False for SELL orders
            apply_adjustment: Whether to apply adjustment (can be disabled)
            
        Returns:
            Adjusted stop loss value
        """
        if not apply_adjustment or settings.spread_adjustment_multiplier == 0:
            return stop_loss
        
        try:
            # Get current spread
            price_data = await self.trading_provider.get_symbol_price(symbol)
            
            spread = price_data['ask'] - price_data['bid']
            adjustment = spread * settings.spread_adjustment_multiplier
            
            logger.debug(f"📊 Spread: {spread:.5f}, Adjustment: {adjustment:.5f} (multiplier: {settings.spread_adjustment_multiplier})")
            
            # Adjust based on order direction
            if is_buy:
                # For BUY: SL is below entry, move it further down
                adjusted_sl = stop_loss - adjustment
            else:
                # For SELL: SL is above entry, move it further up
                adjusted_sl = stop_loss + adjustment
            
            adjusted_sl = round(adjusted_sl, 5)
            
            if abs(adjusted_sl - stop_loss) > 0.00001:
                logger.info(f"📊 SL adjusted for spread: {stop_loss:.5f} → {adjusted_sl:.5f}")
            
            return adjusted_sl
            
        except Exception as e:
            logger.warning(f"⚠️ Could not adjust SL for spread: {e}")
            return stop_loss  # Return original if we can't adjust
    
    async def adjust_sl_for_position(
        self,
        position_id: str,
        stop_loss: float,
        apply_adjustment: bool = True
    ) -> float:
        """
        Adjust SL for an existing position (auto-detects BUY/SELL)
        
        Args:
            position_id: MetaAPI position ID
            stop_loss: Original stop loss value
            apply_adjustment: Whether to apply adjustment
            
        Returns:
            Adjusted stop loss value
        """
        try:
            # Get position to determine symbol and direction
            positions = await self.trading_provider.get_open_positions()
            position = next((p for p in positions if p.get('id') == position_id), None)
            
            if not position:
                logger.warning(f"Position {position_id} not found, cannot adjust for spread")
                return stop_loss
            
            symbol = position.get('symbol')
            is_buy = position.get('type') == 'POSITION_TYPE_BUY'
            
            return await self.adjust_sl_for_spread(symbol, stop_loss, is_buy, apply_adjustment)
            
        except Exception as e:
            logger.warning(f"⚠️ Could not adjust SL for position {position_id}: {e}")
            return stop_loss


# Singleton instance
spread_adjustment_service = SpreadAdjustmentService()
