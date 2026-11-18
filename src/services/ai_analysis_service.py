"""
AI Analysis Service
Saves AI market analysis to database and sends Telegram notifications
"""
from typing import Optional
from datetime import datetime
import json
from loguru import logger

from src.core.database_service import db_service
from src.integrations.telegram.unified_sender import notification_sender


class AIAnalysisService:
    """Service to save and track AI market analysis"""
    
    def __init__(self):
        # Track last notification state per position to avoid spam
        self._last_notification_state = {}  # {position_id: {recommendations_hash, timestamp}}
        # Track last saved analysis state per position to avoid redundant DB writes
        self._last_saved_state = {}  # {position_id: {state_hash, timestamp}}
    
    async def save_analysis(
        self,
        symbol: str,
        position_type: str,
        analysis: dict,
        position_id: Optional[str] = None,
        trade_id: Optional[str] = None,
        profit_pips: Optional[float] = None,
        current_price: Optional[float] = None,
        send_notification: bool = True
    ) -> Optional[str]:
        """
        Save AI market analysis to database
        
        Args:
            symbol: Trading symbol
            position_type: BUY or SELL
            analysis: AI analysis dictionary
            position_id: MetaAPI position ID (optional)
            trade_id: Database trade ID (optional)
            profit_pips: Current profit in pips (optional)
            current_price: Current market price (optional)
            send_notification: Whether to send Telegram notification
            
        Returns:
            Analysis ID if saved successfully
        """
        try:
            # Extract analysis data
            trend = analysis.get('trend', 'unknown')
            volatility = analysis.get('volatility', 'unknown')
            momentum = analysis.get('momentum', 'unknown')
            trend_strength = analysis.get('trend_strength')
            volatility_percent = analysis.get('volatility_percent')
            
            # Extract recommendations
            recommend_breakeven = analysis.get('recommend_breakeven', False)
            tp_recs = analysis.get('tp_recommendations', {})
            adjust_tp_value = tp_recs.get('adjust_tp')  # 'higher', 'lower', or None
            recommend_tp_adjustment = bool(adjust_tp_value)
            recommend_tp_direction = adjust_tp_value  # 'higher' or 'lower'
            recommend_reduce_position = tp_recs.get('reduce_position', False)
            recommend_tight_stop = tp_recs.get('tight_stop', False)
            keep_position_open = tp_recs.get('keep_open', True)
            
            # Calculate confidence (based on trend strength or default)
            confidence = trend_strength if trend_strength is not None else 0.7
            
            # Check if analysis state has changed - only save if changed
            if not self._has_analysis_state_changed(position_id, analysis):
                logger.debug(f"💾 Skipping DB save for {symbol} - analysis unchanged")
                # Return None to indicate no new record was created
                return None
            
            # Save to database (only if state changed)
            market_analysis = await db_service.db.marketanalysis.create(
                data={
                    'symbol': symbol,
                    'positionType': position_type,
                    'positionId': position_id,
                    'trend': trend,
                    'volatility': volatility,
                    'momentum': momentum,
                    'trendStrength': trend_strength,
                    'volatilityPercent': volatility_percent,
                    'recommendBreakeven': recommend_breakeven,
                    'recommendTpAdjustment': recommend_tp_adjustment,
                    'recommendTpDirection': recommend_tp_direction if recommend_tp_adjustment else None,
                    'recommendReducePosition': recommend_reduce_position,
                    'recommendTightStop': recommend_tight_stop,
                    'keepPositionOpen': keep_position_open,
                    'confidence': confidence,
                    'analysisType': 'POSITION',
                    'candlesAnalyzed': analysis.get('candles_analyzed'),
                    'timeframe': analysis.get('timeframe', '1H'),
                    'tradeId': trade_id,
                    'profitPips': profit_pips,
                    'currentPrice': current_price,
                    'actionTaken': False,  # Will be updated when action is taken
                    'notificationSent': False
                }
            )
            
            logger.info(f"💾 Market analysis saved: {market_analysis.id} (status changed)")
            
            # Update saved state tracking
            if position_id:
                state_hash = self._get_recommendation_state_hash(analysis)
                self._last_saved_state[position_id] = {
                    'state_hash': state_hash,
                    'timestamp': datetime.now()
                }
            
            # Send Telegram notification if enabled and status changed
            if send_notification and self._should_notify(analysis):
                # Check if notification state has changed
                if self._has_notification_state_changed(position_id, analysis):
                    await self._send_analysis_notification(
                        symbol=symbol,
                        position_type=position_type,
                        analysis=analysis,
                        profit_pips=profit_pips,
                        analysis_id=market_analysis.id,
                        position_id=position_id
                    )
                else:
                    logger.debug(f"🔕 Skipping notification for {symbol} - status unchanged")
            
            return market_analysis.id
            
        except Exception as e:
            logger.error(f"Failed to save AI analysis: {str(e)}")
            logger.exception(e)
            return None
    
    async def update_analysis_action(
        self,
        analysis_id: str,
        action_type: str,
        action_details: dict
    ) -> bool:
        """
        Update analysis record when an action is taken
        
        Args:
            analysis_id: Analysis record ID
            action_type: Type of action (AI_BREAKEVEN, AI_TP_EXTENSION, AI_PARTIAL_CLOSE)
            action_details: Dictionary with action details
            
        Returns:
            True if updated successfully
        """
        try:
            await db_service.db.marketanalysis.update(
                where={'id': analysis_id},
                data={
                    'actionTaken': True,
                    'actionType': action_type,
                    'actionDetails': json.dumps(action_details)
                }
            )
            logger.debug(f"💾 Analysis {analysis_id} updated with action: {action_type}")
            return True
        except Exception as e:
            logger.error(f"Failed to update analysis action: {str(e)}")
            return False
    
    def _should_notify(self, analysis: dict) -> bool:
        """Check if notification should be sent based on analysis"""
        # Send notification if any recommendation is made
        if analysis.get('recommend_breakeven'):
            return True
        
        tp_recs = analysis.get('tp_recommendations', {})
        if tp_recs.get('adjust_tp') or tp_recs.get('reduce_position'):
            return True
        
        # Send if trend is strong (either direction)
        trend = analysis.get('trend', '')
        if 'strong' in trend:
            return True
        
        return False
    
    def _get_recommendation_state_hash(self, analysis: dict) -> str:
        """Generate a hash of the current recommendations to detect changes"""
        # Create a string representation of current recommendations
        state = {
            'trend': analysis.get('trend', ''),
            'recommend_breakeven': analysis.get('recommend_breakeven', False),
            'adjust_tp': analysis.get('tp_recommendations', {}).get('adjust_tp', False),
            'reduce_position': analysis.get('tp_recommendations', {}).get('reduce_position', False),
            'tight_stop': analysis.get('tp_recommendations', {}).get('tight_stop', False)
        }
        # Convert to sorted string for consistent hashing
        return json.dumps(state, sort_keys=True)
    
    def _has_analysis_state_changed(self, position_id: Optional[str], analysis: dict) -> bool:
        """Check if analysis state has changed since last save (for database writes)"""
        if not position_id:
            # If no position_id, always save (fallback for general analysis)
            return True
        
        current_state_hash = self._get_recommendation_state_hash(analysis)
        
        # Check if we have previous state
        if position_id not in self._last_saved_state:
            # First time - save to database
            return True
        
        # Check if state has changed
        previous_state_hash = self._last_saved_state[position_id].get('state_hash')
        if previous_state_hash != current_state_hash:
            # State changed - save to database
            return True
        
        # State unchanged - skip database write
        return False
    
    def _has_notification_state_changed(self, position_id: Optional[str], analysis: dict) -> bool:
        """Check if notification state has changed since last notification"""
        if not position_id:
            # If no position_id, always send (fallback to original behavior)
            return True
        
        current_state_hash = self._get_recommendation_state_hash(analysis)
        
        # Check if we have previous state
        if position_id not in self._last_notification_state:
            # First time - send notification
            return True
        
        # Check if state has changed
        previous_state_hash = self._last_notification_state[position_id].get('state_hash')
        if previous_state_hash != current_state_hash:
            # State changed - send notification
            return True
        
        # State unchanged - don't spam
        return False
    
    async def _send_analysis_notification(
        self,
        symbol: str,
        position_type: str,
        analysis: dict,
        profit_pips: Optional[float],
        analysis_id: str,
        position_id: Optional[str] = None
    ):
        """Send Telegram notification with AI analysis"""
        try:
            trend = analysis.get('trend', 'unknown')
            volatility = analysis.get('volatility', 'unknown')
            momentum = analysis.get('momentum', 'unknown')
            
            # Build emoji indicators
            trend_emoji = self._get_trend_emoji(trend, position_type)
            volatility_emoji = self._get_volatility_emoji(volatility)
            
            # Build message
            message_parts = [
                "🤖 <b>AI MARKET ANALYSIS</b>",
                "",
                f"📊 <b>{symbol}</b> ({position_type})",
                f"💰 Profit: <b>{profit_pips:+.1f} pips</b>" if profit_pips else "",
                "",
                f"{trend_emoji} Trend: <b>{trend.upper()}</b>",
                f"{volatility_emoji} Volatility: <b>{volatility.upper()}</b>",
                f"⚡ Momentum: <b>{momentum.upper()}</b>",
            ]
            
            # Add recommendations
            recommendations = []
            if analysis.get('recommend_breakeven'):
                recommendations.append("🛡️ Move to breakeven")
            
            tp_recs = analysis.get('tp_recommendations', {})
            if tp_recs.get('adjust_tp'):
                direction = tp_recs.get('adjust_tp')
                recommendations.append(f"🎯 Extend TP {direction}")
            
            if tp_recs.get('reduce_position'):
                recommendations.append("📉 Reduce position (take partial profit)")
            
            if tp_recs.get('tight_stop'):
                recommendations.append("🔒 Tighten stop loss")
            
            if recommendations:
                message_parts.append("")
                message_parts.append("<b>🔮 AI Recommendations:</b>")
                for rec in recommendations:
                    message_parts.append(f"  • {rec}")
            
            # Add disclaimer
            message_parts.extend([
                "",
                "<i>📢 Status changed - you'll only receive updates when recommendations change</i>"
            ])
            
            message = "\n".join([p for p in message_parts if p])  # Filter empty strings
            
            # Send notification
            await notification_sender.send_message(message, parse_mode='html', category='ai_analysis')
            
            # Update database
            await db_service.db.marketanalysis.update(
                where={'id': analysis_id},
                data={
                    'notificationSent': True,
                    'notifiedAt': datetime.now()
                }
            )
            
            # Update notification state tracking to prevent spam
            if position_id:
                state_hash = self._get_recommendation_state_hash(analysis)
                self._last_notification_state[position_id] = {
                    'state_hash': state_hash,
                    'timestamp': datetime.now()
                }
                logger.debug(f"📝 Updated notification state for position {position_id[:8]}...")
            
            logger.debug(f"📱 AI analysis notification sent for {symbol}")
            
        except Exception as e:
            logger.error(f"Failed to send AI analysis notification: {str(e)}")
    
    def _get_trend_emoji(self, trend: str, position_type: str) -> str:
        """Get emoji for trend based on position type"""
        trend_lower = trend.lower()
        is_buy = position_type == 'BUY'
        
        if 'strong_up' in trend_lower:
            return "🟢🟢" if is_buy else "🔴🔴"
        elif 'up' in trend_lower:
            return "🟢" if is_buy else "🔴"
        elif 'down' in trend_lower:
            return "🔴" if is_buy else "🟢"
        elif 'strong_down' in trend_lower:
            return "🔴🔴" if is_buy else "🟢🟢"
        else:
            return "⚪"
    
    def _get_volatility_emoji(self, volatility: str) -> str:
        """Get emoji for volatility"""
        volatility_lower = volatility.lower()
        
        if 'high' in volatility_lower:
            return "🔥"
        elif 'medium' in volatility_lower:
            return "📊"
        else:
            return "💤"
    
    async def get_latest_analysis(self, symbol: str, limit: int = 5) -> list:
        """Get latest analysis for a symbol"""
        try:
            analyses = await db_service.db.marketanalysis.find_many(
                where={'symbol': symbol},
                order={'createdAt': 'desc'},
                take=limit
            )
            return analyses
        except Exception as e:
            logger.error(f"Failed to get latest analysis: {str(e)}")
            return []
    
    async def get_analysis_for_trade(self, trade_id: str) -> list:
        """Get all analysis records for a specific trade"""
        try:
            analyses = await db_service.db.marketanalysis.find_many(
                where={'tradeId': trade_id},
                order={'createdAt': 'desc'}
            )
            return analyses
        except Exception as e:
            logger.error(f"Failed to get trade analysis: {str(e)}")
            return []
    
    def clear_position_state(self, position_id: str):
        """Clear analysis and notification state for a closed position to free memory"""
        if position_id in self._last_notification_state:
            del self._last_notification_state[position_id]
            logger.debug(f"🗑️ Cleared notification state for position {position_id[:8]}...")
        
        if position_id in self._last_saved_state:
            del self._last_saved_state[position_id]
            logger.debug(f"🗑️ Cleared saved analysis state for position {position_id[:8]}...")


# Singleton instance
ai_analysis_service = AIAnalysisService()
