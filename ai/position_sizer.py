"""
AI Position Sizer
Dynamically calculates optimal lot size based on market conditions and database settings
"""
import json
import time
from datetime import datetime, timezone
from loguru import logger

from src.core.database_service import db_service


class AIPositionSizer:
    """AI-powered position sizing with database integration"""
    
    def __init__(self):
        self._config_cache = None
        self._config_cache_time = None
        self._config_cache_ttl = 60  # Cache config for 60 seconds
    
    async def get_config(self) -> dict:
        """Get AI configuration from database with caching"""
        try:
            # Check cache
            if self._config_cache and self._config_cache_time:
                age = (datetime.now(timezone.utc) - self._config_cache_time).total_seconds()
                if age < self._config_cache_ttl:
                    return self._config_cache
            
            # Fetch from database
            config = await db_service.db.aiconfiguration.find_first()
            
            if not config:
                logger.warning("No AI configuration found, using defaults")
                return self._get_default_config()
            
            # Convert to dict and cache
            config_dict = {
                'enablePositionSizing': config.enablePositionSizing,
                'baseRiskPercent': config.baseRiskPercent,
                'minLotSize': config.minLotSize,
                'maxLotSize': config.maxLotSize,
                'volatilityMultiplier': config.volatilityMultiplier,
            }
            
            self._config_cache = config_dict
            self._config_cache_time = datetime.now(timezone.utc)
            
            return config_dict
            
        except Exception as e:
            logger.error(f"Failed to get AI config from database: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> dict:
        """Get default configuration"""
        return {
            'enablePositionSizing': True,
            'baseRiskPercent': 2.0,
            'minLotSize': 0.01,
            'maxLotSize': 1.0,
            'volatilityMultiplier': 1.0,
        }
    
    async def calculate_optimal_lot_size(
        self,
        signal: dict,
        market_analysis: dict,
        account_equity: float
    ) -> dict:
        """
        Calculate optimal lot size based on:
        - Account risk (from config)
        - Market volatility
        - Trend strength
        - Stop loss distance
        
        Args:
            signal: Signal with entry, SL, TP
            market_analysis: AI market analysis
            account_equity: Current account balance
            
        Returns:
            {
                'lot_size': float,
                'confidence': float,
                'reason': str,
                'decision_id': str,
                'calculations': dict
            }
        """
        start_time = time.time()
        
        try:
            config = await self.get_config()
            
            # Check if position sizing is enabled
            if not config.get('enablePositionSizing', True):
                logger.debug("AI position sizing disabled in config")
                return {
                    'lot_size': config.get('minLotSize', 0.01),
                    'confidence': 1.0,
                    'reason': 'Position sizing disabled, using minimum lot size',
                    'calculations': {}
                }
            
            logger.info(f"🤖 AI calculating optimal lot size for {signal.get('symbol')}...")
            
            # Prepare input data
            input_data = {
                'signal': {
                    'symbol': signal.get('symbol'),
                    'type': signal.get('signalType'),
                    'entry': signal.get('entryPrice'),
                    'sl': signal.get('stopLoss'),
                },
                'account_equity': account_equity,
                'market_analysis': {
                    'trend': market_analysis.get('trend'),
                    'volatility': market_analysis.get('volatility'),
                    'trend_strength': market_analysis.get('trend_strength'),
                }
            }
            
            # 1. Base risk amount
            base_risk_percent = config.get('baseRiskPercent', 2.0)
            base_risk_amount = account_equity * (base_risk_percent / 100)
            
            # 2. Get risk multipliers from market conditions
            volatility_multiplier = self._get_volatility_multiplier(
                market_analysis,
                config.get('volatilityMultiplier', 1.0)
            )
            trend_multiplier = self._get_trend_multiplier(market_analysis, signal)
            
            # 3. Adjust risk amount
            adjusted_risk = base_risk_amount * volatility_multiplier * trend_multiplier
            
            # 4. Calculate lot size based on SL distance
            # Support both camelCase and snake_case key conventions
            entry = signal.get('entryPrice') or signal.get('entry_price', 0)
            sl    = signal.get('stopLoss')   or signal.get('stop_loss', 0)

            # Derive entry from range bounds if still missing
            if not entry:
                r_min = signal.get('entryRangeMin') or signal.get('entry_range_min')
                r_max = signal.get('entryRangeMax') or signal.get('entry_range_max')
                if r_min and r_max:
                    entry = (r_min + r_max) / 2
                    logger.info(f"📊 AI sizer: range midpoint {entry:.5f} ({r_min} – {r_max})")
                elif r_min or r_max:
                    entry = r_min or r_max
                    logger.warning(f"⚠️ AI sizer: partial range, using {entry:.5f}")
            
            if not entry or not sl:
                logger.warning("Missing entry or SL - using minimum lot size")
                return await self._save_decision(
                    lot_size=config.get('minLotSize', 0.01),
                    confidence=0.5,
                    reason='Missing entry or SL, using minimum lot size',
                    input_data=input_data,
                    signal=signal,
                    calculations={},
                    execution_time_ms=int((time.time() - start_time) * 1000)
                )
            
            symbol = signal.get('symbol')
            pip_value = self._get_pip_value(symbol)
            sl_distance_pips = abs(entry - sl) / pip_value
            
            # Lot size = Risk Amount / (SL Distance in pips × pip value per lot)
            # For standard lot: $10 per pip
            # For mini lot: $1 per pip
            # For micro lot: $0.10 per pip
            pip_value_per_lot = 10  # Standard lot
            
            if sl_distance_pips > 0:
                lot_size = adjusted_risk / (sl_distance_pips * pip_value_per_lot)
            else:
                lot_size = config.get('minLotSize', 0.01)
            
            # 5. Round and clamp
            lot_size = round(lot_size, 2)
            min_lot = config.get('minLotSize', 0.01)
            max_lot = config.get('maxLotSize', 1.0)
            lot_size = max(min_lot, min(lot_size, max_lot))
            
            # 6. Prepare calculations for logging
            calculations = {
                'base_risk_amount': base_risk_amount,
                'base_risk_percent': base_risk_percent,
                'volatility_multiplier': volatility_multiplier,
                'trend_multiplier': trend_multiplier,
                'adjusted_risk': adjusted_risk,
                'sl_distance_pips': sl_distance_pips,
                'pip_value': pip_value,
                'raw_lot_size': adjusted_risk / (sl_distance_pips * pip_value_per_lot) if sl_distance_pips > 0 else 0,
                'final_lot_size': lot_size,
            }
            
            logger.success(
                f"✅ AI Position Size: {lot_size} lots "
                f"(base: ${base_risk_amount:.2f}, "
                f"volatility: {volatility_multiplier:.2f}x, "
                f"trend: {trend_multiplier:.2f}x)"
            )
            
            return await self._save_decision(
                lot_size=lot_size,
                confidence=0.9,
                reason=f'Calculated based on {base_risk_percent}% risk with market adjustments',
                input_data=input_data,
                signal=signal,
                calculations=calculations,
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
            
        except Exception as e:
            logger.error(f"❌ AI position sizing error: {e}")
            logger.exception(e)
            # Fail-safe: return minimum lot size
            return {
                'lot_size': 0.01,
                'confidence': 0.5,
                'reason': f'Position sizing failed: {e}',
                'calculations': {}
            }
    
    def _get_volatility_multiplier(self, market_analysis: dict, base_multiplier: float) -> float:
        """Get risk multiplier based on volatility"""
        volatility = market_analysis.get('volatility', 'medium')
        
        if volatility == 'high':
            return 0.5 * base_multiplier  # Reduce size by 50% in high volatility
        elif volatility == 'low':
            return 1.5 * base_multiplier  # Increase size by 50% in low volatility
        else:
            return 1.0 * base_multiplier  # Normal size
    
    def _get_trend_multiplier(self, market_analysis: dict, signal: dict) -> float:
        """Get risk multiplier based on trend strength"""
        trend_strength = market_analysis.get('trend_strength', 0.5)
        trend = market_analysis.get('trend', 'sideways')
        signal_type = signal.get('signalType')
        
        # Check if signal aligns with trend
        aligned = False
        if signal_type == 'BUY' and trend in ['up', 'strong_up']:
            aligned = True
        elif signal_type == 'SELL' and trend in ['down', 'strong_down']:
            aligned = True
        
        if aligned and trend_strength > 0.8:
            return 1.2  # Increase size by 20% for strong aligned trend
        elif not aligned:
            return 0.7  # Reduce size by 30% for counter-trend
        else:
            return 1.0  # Normal size
    
    def _get_pip_value(self, symbol: str) -> float:
        """Get pip value for symbol"""
        from src.utils.pip_utils import get_pip_size
        return get_pip_size(symbol)
    
    async def _save_decision(
        self,
        lot_size: float,
        confidence: float,
        reason: str,
        input_data: dict,
        signal: dict,
        calculations: dict,
        execution_time_ms: int
    ) -> dict:
        """Save AI decision to database"""
        try:
            # Prepare output data
            output_data = {
                'lot_size': lot_size,
                'calculations': calculations
            }
            
            # Create decision record
            decision_record = await db_service.db.aidecision.create(data={
                'decisionType': 'POSITION_SIZING',
                'decision': 'CALCULATED',
                'confidence': confidence,
                'reason': reason,
                'inputData': json.dumps(input_data),
                'outputData': json.dumps(output_data),
                'signalId': signal.get('id'),
                'symbol': signal.get('symbol'),
                'outcome': 'PENDING',
                'executionTimeMs': execution_time_ms,
            })
            
            logger.debug(f"💾 Saved AI position sizing decision: {decision_record.id}")
            
            # Return result
            return {
                'lot_size': lot_size,
                'confidence': confidence,
                'reason': reason,
                'decision_id': decision_record.id,
                'calculations': calculations
            }
            
        except Exception as e:
            logger.error(f"Failed to save AI decision: {e}")
            # Return result even if save fails
            return {
                'lot_size': lot_size,
                'confidence': confidence,
                'reason': reason,
                'calculations': calculations
            }
