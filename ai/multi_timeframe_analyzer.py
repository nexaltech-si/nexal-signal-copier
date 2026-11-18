"""
AI Multi-Timeframe Analyzer
Analyzes multiple timeframes for comprehensive market view with database configuration
"""
import json
import time
from typing import Optional
from datetime import datetime, timezone
from loguru import logger

from src.core.database_service import db_service


class AIMultiTimeframeAnalyzer:
    """
    AI-powered multi-timeframe analysis with database configuration
    Analyzes 4H, 1H, and 15M timeframes for trend confirmation
    """
    
    def __init__(self, market_analyzer):
        self.market_analyzer = market_analyzer
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
                'enableMultiTimeframe': config.enableMultiTimeframe,
                'enableH4Analysis': config.enableH4Analysis,
                'enableH1Analysis': config.enableH1Analysis,
                'enableM15Analysis': config.enableM15Analysis,
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
            'enableMultiTimeframe': False,
            'enableH4Analysis': True,
            'enableH1Analysis': True,
            'enableM15Analysis': False,
        }
    
    async def analyze_all_timeframes(
        self,
        symbol: str,
        position_type: Optional[str] = None,
        metaapi_connection = None
    ) -> dict:
        """
        Analyze multiple timeframes for comprehensive view
        
        Args:
            symbol: Trading symbol (e.g., 'EURUSD')
            position_type: 'BUY' or 'SELL' (optional)
            metaapi_connection: MetaAPI connection for fetching candles
            
        Returns:
            {
                'enabled': bool,
                'overall_trend': str,
                'overall_confidence': float,
                'h4': dict,
                'h1': dict,
                'm15': dict,
                'recommendation': str,
                'reason': str,
                'decision_id': str
            }
        """
        start_time = time.time()
        
        try:
            config = await self.get_config()
            
            # Check if multi-timeframe is enabled
            if not config.get('enableMultiTimeframe', False):
                logger.debug("Multi-timeframe analysis disabled in config")
                return {
                    'enabled': False,
                    'overall_trend': 'unknown',
                    'overall_confidence': 0.5,
                    'reason': 'Multi-timeframe analysis disabled',
                    'h4': {},
                    'h1': {},
                    'm15': {}
                }
            
            logger.info(f"🤖 AI analyzing multiple timeframes for {symbol}...")
            
            # Prepare input data
            input_data = {
                'symbol': symbol,
                'position_type': position_type,
                'timeframes_enabled': {
                    'h4': config.get('enableH4Analysis', True),
                    'h1': config.get('enableH1Analysis', True),
                    'm15': config.get('enableM15Analysis', False),
                }
            }
            
            # Analyze each enabled timeframe
            h4_analysis = {}
            h1_analysis = {}
            m15_analysis = {}
            
            # 4H Analysis (Higher timeframe - Overall trend)
            if config.get('enableH4Analysis', True):
                logger.debug("  📊 Analyzing 4H timeframe...")
                h4_analysis = await self._analyze_timeframe(
                    symbol=symbol,
                    timeframe='4h',
                    position_type=position_type,
                    metaapi_connection=metaapi_connection
                )
            
            # 1H Analysis (Medium timeframe - Entry confirmation)
            if config.get('enableH1Analysis', True):
                logger.debug("  📊 Analyzing 1H timeframe...")
                h1_analysis = await self._analyze_timeframe(
                    symbol=symbol,
                    timeframe='1h',
                    position_type=position_type,
                    metaapi_connection=metaapi_connection
                )
            
            # 15M Analysis (Lower timeframe - Entry timing)
            if config.get('enableM15Analysis', False):
                logger.debug("  📊 Analyzing 15M timeframe...")
                m15_analysis = await self._analyze_timeframe(
                    symbol=symbol,
                    timeframe='15m',
                    position_type=position_type,
                    metaapi_connection=metaapi_connection
                )
            
            # Combine analysis
            combined = self._combine_timeframe_analysis(h4_analysis, h1_analysis, m15_analysis)
            
            logger.success(
                f"✅ Multi-Timeframe Analysis: {combined['overall_trend']} "
                f"(confidence: {combined['overall_confidence']:.2f})"
            )
            
            # Save decision to database
            result = await self._save_decision(
                symbol=symbol,
                position_type=position_type,
                h4_analysis=h4_analysis,
                h1_analysis=h1_analysis,
                m15_analysis=m15_analysis,
                combined=combined,
                input_data=input_data,
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Multi-timeframe analysis error: {e}")
            logger.exception(e)
            # Fail-safe: return neutral analysis
            return {
                'enabled': True,
                'overall_trend': 'unknown',
                'overall_confidence': 0.5,
                'reason': f'Analysis failed: {e}',
                'h4': {},
                'h1': {},
                'm15': {}
            }
    
    async def _analyze_timeframe(
        self,
        symbol: str,
        timeframe: str,
        position_type: Optional[str] = None,
        metaapi_connection = None
    ) -> dict:
        """Analyze a single timeframe"""
        try:
            # Use existing market analyzer
            analysis = await self.market_analyzer.analyze_market_condition(
                symbol=symbol,
                position_type=position_type,
                metaapi_connection=metaapi_connection,
                timeframe=timeframe
            )
            
            if analysis.get('error'):
                logger.warning(f"Failed to analyze {timeframe}: {analysis['error']}")
                return {
                    'timeframe': timeframe,
                    'trend': 'unknown',
                    'volatility': 'unknown',
                    'momentum': 'unknown',
                    'trend_strength': 0.5,
                    'error': analysis['error']
                }
            
            return {
                'timeframe': timeframe,
                'trend': analysis.get('trend', 'unknown'),
                'volatility': analysis.get('volatility', 'unknown'),
                'momentum': analysis.get('momentum', 'unknown'),
                'trend_strength': analysis.get('trend_strength', 0.5),
                'volatility_percent': analysis.get('volatility_percent', 0),
                'candles_analyzed': analysis.get('candles_analyzed', 0),
            }
            
        except Exception as e:
            logger.error(f"Error analyzing {timeframe}: {e}")
            return {
                'timeframe': timeframe,
                'trend': 'unknown',
                'volatility': 'unknown',
                'momentum': 'unknown',
                'trend_strength': 0.5,
                'error': str(e)
            }
    
    def _combine_timeframe_analysis(
        self,
        h4_analysis: dict,
        h1_analysis: dict,
        m15_analysis: dict
    ) -> dict:
        """
        Combine multi-timeframe analysis into overall assessment
        
        Logic:
        - 4H defines overall trend direction
        - 1H confirms or conflicts with 4H
        - 15M provides entry timing
        """
        try:
            h4_trend = h4_analysis.get('trend', 'unknown')
            h1_trend = h1_analysis.get('trend', 'unknown')
            m15_trend = m15_analysis.get('trend', 'unknown')
            
            h4_strength = h4_analysis.get('trend_strength', 0.5)
            h1_strength = h1_analysis.get('trend_strength', 0.5)
            
            # Determine overall trend
            overall_trend = 'unknown'
            overall_confidence = 0.5
            recommendation = 'NEUTRAL'
            reason = ''
            
            # Case 1: All timeframes align (strongest signal)
            if h4_trend == h1_trend and (not m15_analysis or m15_trend == h4_trend):
                if h4_trend in ['up', 'strong_up']:
                    overall_trend = 'strong_up'
                    overall_confidence = 0.95
                    recommendation = 'STRONG_BUY'
                    reason = 'All timeframes aligned upward'
                elif h4_trend in ['down', 'strong_down']:
                    overall_trend = 'strong_down'
                    overall_confidence = 0.95
                    recommendation = 'STRONG_SELL'
                    reason = 'All timeframes aligned downward'
                else:
                    overall_trend = 'sideways'
                    overall_confidence = 0.7
                    recommendation = 'NEUTRAL'
                    reason = 'All timeframes sideways'
            
            # Case 2: 4H and 1H align (strong signal)
            elif h4_trend == h1_trend:
                if h4_trend in ['up', 'strong_up']:
                    overall_trend = 'up'
                    overall_confidence = 0.85
                    recommendation = 'BUY'
                    reason = '4H and 1H aligned upward'
                elif h4_trend in ['down', 'strong_down']:
                    overall_trend = 'down'
                    overall_confidence = 0.85
                    recommendation = 'SELL'
                    reason = '4H and 1H aligned downward'
                else:
                    overall_trend = 'sideways'
                    overall_confidence = 0.6
                    recommendation = 'NEUTRAL'
                    reason = '4H and 1H sideways'
            
            # Case 3: 4H strong, 1H weak (follow 4H)
            elif h4_strength > 0.7 and h1_strength < 0.5:
                overall_trend = h4_trend
                overall_confidence = 0.7
                if h4_trend in ['up', 'strong_up']:
                    recommendation = 'BUY'
                    reason = '4H strong uptrend, 1H weak'
                elif h4_trend in ['down', 'strong_down']:
                    recommendation = 'SELL'
                    reason = '4H strong downtrend, 1H weak'
                else:
                    recommendation = 'NEUTRAL'
                    reason = '4H sideways, 1H weak'
            
            # Case 4: Conflicting trends (caution)
            elif (h4_trend in ['up', 'strong_up'] and h1_trend in ['down', 'strong_down']) or \
                 (h4_trend in ['down', 'strong_down'] and h1_trend in ['up', 'strong_up']):
                overall_trend = 'conflicting'
                overall_confidence = 0.4
                recommendation = 'AVOID'
                reason = f'Conflicting trends: 4H {h4_trend}, 1H {h1_trend}'
            
            # Case 5: Default to 1H if 4H unknown
            elif h4_trend == 'unknown' and h1_trend != 'unknown':
                overall_trend = h1_trend
                overall_confidence = 0.6
                if h1_trend in ['up', 'strong_up']:
                    recommendation = 'BUY'
                elif h1_trend in ['down', 'strong_down']:
                    recommendation = 'SELL'
                else:
                    recommendation = 'NEUTRAL'
                reason = '4H unavailable, using 1H'
            
            # Default
            else:
                overall_trend = 'unknown'
                overall_confidence = 0.5
                recommendation = 'NEUTRAL'
                reason = 'Insufficient data for analysis'
            
            return {
                'overall_trend': overall_trend,
                'overall_confidence': overall_confidence,
                'recommendation': recommendation,
                'reason': reason,
                'timeframe_alignment': {
                    'h4': h4_trend,
                    'h1': h1_trend,
                    'm15': m15_trend if m15_analysis else 'disabled',
                    'aligned': h4_trend == h1_trend
                }
            }
            
        except Exception as e:
            logger.error(f"Error combining timeframe analysis: {e}")
            return {
                'overall_trend': 'unknown',
                'overall_confidence': 0.5,
                'recommendation': 'NEUTRAL',
                'reason': f'Combination failed: {e}',
                'timeframe_alignment': {}
            }
    
    async def _save_decision(
        self,
        symbol: str,
        position_type: Optional[str],
        h4_analysis: dict,
        h1_analysis: dict,
        m15_analysis: dict,
        combined: dict,
        input_data: dict,
        execution_time_ms: int
    ) -> dict:
        """Save multi-timeframe analysis to database"""
        try:
            # Prepare output data
            output_data = {
                'h4': h4_analysis,
                'h1': h1_analysis,
                'm15': m15_analysis,
                'combined': combined
            }
            
            # Prepare market data
            market_data = {
                'overall_trend': combined['overall_trend'],
                'overall_confidence': combined['overall_confidence'],
                'recommendation': combined['recommendation'],
                'timeframe_alignment': combined.get('timeframe_alignment', {})
            }
            
            # Create decision record
            decision_record = await db_service.db.aidecision.create(data={
                'decisionType': 'MULTI_TIMEFRAME_ANALYSIS',
                'decision': combined['recommendation'],
                'confidence': combined['overall_confidence'],
                'reason': combined['reason'],
                'inputData': json.dumps(input_data),
                'outputData': json.dumps(output_data),
                'marketData': json.dumps(market_data),
                'symbol': symbol,
                'outcome': 'PENDING',
                'executionTimeMs': execution_time_ms,
            })
            
            logger.debug(f"💾 Saved multi-timeframe analysis: {decision_record.id}")
            
            # Return complete result
            return {
                'enabled': True,
                'overall_trend': combined['overall_trend'],
                'overall_confidence': combined['overall_confidence'],
                'recommendation': combined['recommendation'],
                'reason': combined['reason'],
                'decision_id': decision_record.id,
                'h4': h4_analysis,
                'h1': h1_analysis,
                'm15': m15_analysis,
                'timeframe_alignment': combined.get('timeframe_alignment', {})
            }
            
        except Exception as e:
            logger.error(f"Failed to save multi-timeframe analysis: {e}")
            # Return result even if save fails
            return {
                'enabled': True,
                'overall_trend': combined['overall_trend'],
                'overall_confidence': combined['overall_confidence'],
                'recommendation': combined['recommendation'],
                'reason': combined['reason'],
                'h4': h4_analysis,
                'h1': h1_analysis,
                'm15': m15_analysis,
                'timeframe_alignment': combined.get('timeframe_alignment', {})
            }
