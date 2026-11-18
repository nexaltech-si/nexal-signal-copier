"""
AI-based market condition analyzer
Uses MetaAPI for market data retrieval.
Supports both numerical (NumPy MA-cross) and LLM-powered analysis.
"""
import logging
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None
    logger.warning("NumPy not available - market analysis will be limited")

class MarketAnalyzer:
    """AI-powered market analyzer for trade management decisions"""
    
    def __init__(self, config):
        self.config = config
        self._llm_client = None
        self._llm_client_initialized = False
        self._last_llm_call: Dict[str, datetime] = {}  # {symbol: timestamp} for rate limiting
    
    @property
    def _use_llm(self) -> bool:
        """Check if LLM-powered market analysis is enabled."""
        return getattr(self.config, 'enable_llm_market_analysis', False)
    
    @property
    def _llm_interval(self) -> int:
        """Minimum seconds between LLM calls per symbol."""
        return getattr(self.config, 'llm_market_analysis_interval', 60)
    
    def _get_llm_client(self):
        """Lazy-initialize LLM client using shared factory."""
        if not self._llm_client_initialized:
            from ai.llm_client import build_llm_client, get_llm_model
            self._llm_client = build_llm_client(self.config)
            self._llm_model = get_llm_model(self.config)
            self._llm_client_initialized = True
            if self._llm_client:
                logger.info(f"✅ LLM market analysis client ready: {self._llm_model}")
            else:
                logger.warning("⚠️ LLM market analysis: no LLM client available")
        return self._llm_client
    
    def _can_call_llm(self, symbol: str) -> bool:
        """Rate-limit LLM calls per symbol."""
        now = datetime.now()
        last = self._last_llm_call.get(symbol)
        if last and (now - last).total_seconds() < self._llm_interval:
            return False
        self._last_llm_call[symbol] = now
        return True
    
    async def analyze_market_condition(self, symbol: str, position_type=None, metaapi_connection=None, timeframe: str = '1h') -> Dict[str, Any]:
        """Analyze market conditions and provide recommendations
        
        Args:
            symbol: Symbol to analyze
            position_type: Optional position type for context
            metaapi_connection: MetaAPI connection to fetch candles
            timeframe: Timeframe to analyze ('4h', '1h', '15m', etc.)
            
        Returns:
            Dict with analysis and recommendations
        """
        if not NUMPY_AVAILABLE:
            return {"error": "NumPy not installed. Market analysis not available."}
        
        try:
            # Get market data from MetaAPI
            candles = await self._get_market_data(symbol, metaapi_connection, timeframe)
            if not candles or len(candles) < 50:
                return {"error": "Insufficient market data"}
            
            # Analyze trend
            trend = self._analyze_trend(candles)
            
            # Calculate volatility
            volatility = self._calculate_volatility(candles)
            
            # Detect momentum
            momentum = self._detect_momentum(candles)
            
            # Make break-even recommendation
            be_recommendation = self._should_move_to_breakeven(
                trend, volatility, momentum, position_type
            )
            
            # Make TP recommendations
            tp_recommendations = self._get_tp_recommendations(
                trend, volatility, momentum, position_type
            )

            # Calculate numeric trend strength (0.0 - 1.0) for confidence scoring
            trend_strength = self._calculate_trend_strength(candles)

            # Calculate raw volatility percent for DB storage
            volatility_percent = self._calculate_volatility_percent(candles)

            return {
                "trend": trend,
                "volatility": volatility,
                "momentum": momentum,
                "recommend_breakeven": be_recommendation,
                "tp_recommendations": tp_recommendations,
                "trend_strength": trend_strength,
                "volatility_percent": volatility_percent,
                "candles_analyzed": len(candles),
                "timeframe": timeframe.upper(),
            }
            
        except Exception as e:
            logger.error(f"Error analyzing market: {e}")
            return {"error": str(e)}
    
    async def _get_market_data(self, symbol: str, metaapi_connection, timeframe: str = '1h'):
        """Get OHLC data from active trading provider
        
        Args:
            symbol: Trading symbol
            metaapi_connection: Active MetaAPI connection (deprecated, kept for compatibility)
            timeframe: Timeframe to fetch ('4h', '1h', '15m', etc.)
            
        Returns:
            List of candles with OHLC data
        """
        try:
            # Import trading service to get active provider
            from src.services.trading_service import trading_service
            
            # Get the active trading provider
            provider = trading_service.trading_provider
            
            if not provider:
                logger.warning("No trading provider available, cannot fetch market data")
                return None
            
            if not provider.is_connected:
                logger.warning("Trading provider not connected, cannot fetch market data")
                return None
            
            # Fetch candles using the provider's method
            candles = await provider.get_historical_candles(
                symbol=symbol,
                timeframe=timeframe,
                limit=100
            )
            
            if not candles:
                logger.warning(f"No candle data received for {symbol}")
                return None
            
            logger.debug(f"Retrieved {len(candles)} candles for {symbol}")
            return candles
            
        except Exception as e:
            logger.error(f"Error fetching market data from trading provider: {e}")
            return None
    
    def _analyze_trend(self, candles):
        """Analyze market trend using moving averages
        
        Args:
            candles: List of MetaAPI candles [{time, open, high, low, close, volume}]
        """
        # Extract close prices from MetaAPI candle format
        close_prices = np.array([candle['close'] for candle in candles])
        
        # Calculate moving averages
        ma_fast = np.mean(close_prices[-20:])  # 20-period MA
        ma_slow = np.mean(close_prices[-50:])  # 50-period MA
        
        # Determine trend direction
        if ma_fast > ma_slow * 1.005:
            return "strong_up"
        elif ma_fast > ma_slow:
            return "up"
        elif ma_fast < ma_slow * 0.995:
            return "strong_down"
        elif ma_fast < ma_slow:
            return "down"
        else:
            return "sideways"
    
    def _calculate_volatility(self, candles):
        """Calculate market volatility
        
        Args:
            candles: List of MetaAPI candles [{time, open, high, low, close, volume}]
        """
        # Calculate price ranges for each candle (high - low)
        ranges = np.array([candle['high'] - candle['low'] for candle in candles])
        
        # Calculate average range as percentage of price
        avg_range = np.mean(ranges[-20:])
        avg_price = np.mean([candle['close'] for candle in candles[-20:]])
        volatility_pct = (avg_range / avg_price) * 100
        
        # Determine volatility level
        if volatility_pct > 1.5:
            return "high"
        elif volatility_pct > 0.7:
            return "medium"
        else:
            return "low"
    
    def _detect_momentum(self, candles):
        """Detect market momentum
        
        Args:
            candles: List of MetaAPI candles [{time, open, high, low, close, volume}]
        """
        # Extract close prices
        close_prices = np.array([candle['close'] for candle in candles])
        
        # Calculate price changes
        price_changes = np.diff(close_prices)
        
        # Calculate momentum score
        recent_changes = price_changes[-10:]
        momentum_score = np.sum(np.sign(recent_changes))
        
        # Determine momentum
        if momentum_score > 5:
            return "strong_up"
        elif momentum_score > 2:
            return "up"
        elif momentum_score < -5:
            return "strong_down"
        elif momentum_score < -2:
            return "down"
        else:
            return "neutral"
    
    def _should_move_to_breakeven(self, trend, volatility, momentum, position_type):
        """Determine if position should be moved to break-even"""
        # Logic based on market conditions and position direction
        if position_type == "BUY":
            # In downtrend or high volatility with down momentum, move to BE
            if (trend in ["down", "strong_down"] or 
                (volatility == "high" and momentum in ["down", "strong_down"])):
                return True
        elif position_type == "SELL":
            # In uptrend or high volatility with up momentum, move to BE
            if (trend in ["up", "strong_up"] or 
                (volatility == "high" and momentum in ["up", "strong_up"])):
                return True
        
        return False
    
    def _get_tp_recommendations(self, trend, volatility, momentum, position_type):
        """Get take profit recommendations"""
        recommendations = {}
        
        # Adjust TP levels based on conditions
        if position_type == "BUY":
            if trend in ["strong_up"] and momentum in ["up", "strong_up"]:
                recommendations["keep_open"] = True  # Hold for higher RR
                recommendations["adjust_tp"] = "higher"
            elif trend in ["down", "strong_down"] or momentum in ["down", "strong_down"]:
                recommendations["reduce_position"] = True  # Take profits sooner
        
        elif position_type == "SELL":
            if trend in ["strong_down"] and momentum in ["down", "strong_down"]:
                recommendations["keep_open"] = True  # Hold for higher RR
                recommendations["adjust_tp"] = "lower"
            elif trend in ["up", "strong_up"] or momentum in ["up", "strong_up"]:
                recommendations["reduce_position"] = True  # Take profits sooner
        
        # Adjust for volatility
        if volatility == "high":
            recommendations["tight_stop"] = True
        
        return recommendations

    def _calculate_trend_strength(self, candles) -> float:
        """Calculate trend strength as a 0.0-1.0 confidence score based on MA separation"""
        close_prices = np.array([candle['close'] for candle in candles])
        ma_fast = np.mean(close_prices[-20:])
        ma_slow = np.mean(close_prices[-50:])
        if ma_slow == 0:
            return 0.0
        separation = abs(ma_fast - ma_slow) / ma_slow
        # Cap at 2% separation = full confidence
        return float(min(separation / 0.02, 1.0))

    def _calculate_volatility_percent(self, candles) -> float:
        """Calculate raw volatility as average candle range percentage of price"""
        ranges = np.array([candle['high'] - candle['low'] for candle in candles])
        avg_range = np.mean(ranges[-20:])
        avg_price = np.mean([candle['close'] for candle in candles[-20:]])
        if avg_price == 0:
            return 0.0
        return float(round((avg_range / avg_price) * 100, 4))
    
    # ── LLM-Powered Analysis ──────────────────────────────────────────────────
    
    async def analyze_market_condition_llm(
        self, symbol: str, position_type=None,
        metaapi_connection=None, timeframe: str = '1h'
    ) -> Dict[str, Any]:
        """
        Analyze market conditions with LLM enrichment.

        Runs numerical analysis first, then augments with LLM reasoning
        if enabled and available. Falls back to numerical-only on any error.

        Returns the standard dict with extra fields: regime, session, adx,
        reasoning, key_support, key_resistance, risk_level, recommendation,
        analysis_source.
        """
        # Always run numerical analysis first
        base = await self.analyze_market_condition(
            symbol, position_type, metaapi_connection, timeframe
        )
        if base.get('error'):
            return base

        # Get candles for regime detection and LLM context
        candles = await self._get_market_data(symbol, metaapi_connection, timeframe)
        if not candles or len(candles) < 30:
            base['analysis_source'] = 'numerical'
            base['regime'] = 'unknown'
            base['session'] = 'off_hours'
            return base

        # Detect regime
        try:
            from ai.market_regime_detector import MarketRegimeDetector
            regime_data = MarketRegimeDetector.detect(candles)
        except Exception as e:
            logger.warning(f"Regime detection failed: {e}")
            regime_data = {'regime': 'unknown', 'adx': 0.0, 'session': 'off_hours', 'volatility_zone': 'medium'}

        # Merge regime data into result
        base['regime'] = regime_data['regime']
        base['session'] = regime_data['session']
        base['adx'] = regime_data['adx']
        base['volatility_zone'] = regime_data['volatility_zone']

        # Try LLM enrichment
        if self._use_llm and self._can_call_llm(symbol):
            llm_enriched = await self._call_llm_analysis(
                symbol, timeframe, base, candles, regime_data
            )
            if llm_enriched:
                base.update(llm_enriched)
                base['analysis_source'] = 'llm'
                return base

        base['analysis_source'] = 'numerical'
        return base

    async def _call_llm_analysis(
        self, symbol: str, timeframe: str,
        base: dict, candles: list, regime_data: dict
    ) -> Optional[Dict[str, Any]]:
        """Call LLM for enriched market analysis. Returns None on failure."""
        client = self._get_llm_client()
        if not client:
            return None

        try:
            from ai.market_analysis_prompts import (
                SYSTEM_PROMPT, build_market_analysis_prompt, parse_llm_analysis_response
            )

            recent_prices = self._build_recent_price_summary(candles)
            user_prompt = build_market_analysis_prompt(
                symbol=symbol,
                timeframe=timeframe,
                numerical_trend=base.get('trend', 'unknown'),
                volatility=base.get('volatility', 'unknown'),
                momentum=base.get('momentum', 'unknown'),
                trend_strength=base.get('trend_strength', 0.5),
                regime=regime_data['regime'],
                adx=regime_data['adx'],
                session=regime_data['session'],
                volatility_zone=regime_data['volatility_zone'],
                recent_prices=recent_prices,
            )

            logger.debug(f"🤖 LLM market analysis request for {symbol} {timeframe}")

            from ai.llm_client import extract_content

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: client.chat.completions.create(
                    model=self._llm_model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.3,
                )
            )

            try:
                from ai.cost_tracker import cost_tracker
                usage = getattr(response, 'usage', None)
                if usage:
                    provider = str(getattr(self.config, 'primary_ai_provider', 'openai')).lower()
                    cost_tracker.record(
                        caller='market_analysis',
                        provider=provider,
                        model=self._llm_model,
                        prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
                        completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
                    )
            except Exception as _exc:
                logger.debug(f"Suppressed exception: {_exc!r}")

            content = extract_content(response)
            parsed = parse_llm_analysis_response(content)

            if parsed:
                logger.info(f"✅ LLM analysis for {symbol}: {parsed.get('recommendation', '?')} "
                           f"(confidence: {parsed.get('confidence', '?')})")
                return {
                    'reasoning': parsed.get('reasoning', ''),
                    'key_support': parsed.get('key_support'),
                    'key_resistance': parsed.get('key_resistance'),
                    'risk_level': parsed.get('risk_level', 'medium'),
                    'recommendation': parsed.get('recommendation', 'neutral'),
                    'llm_trend': parsed.get('trend'),
                    'llm_confidence': parsed.get('confidence'),
                }
            else:
                logger.warning(f"⚠️ LLM analysis: failed to parse response for {symbol}")
                return None

        except Exception as e:
            logger.warning(f"⚠️ LLM market analysis failed for {symbol}: {e}")
            return None

    def _build_recent_price_summary(self, candles: list) -> str:
        """Build a concise price summary for the LLM prompt."""
        if not candles or len(candles) < 5:
            return "No price data available."

        recent = candles[-5:]
        closes = [c['close'] for c in recent]
        highs = [c['high'] for c in recent]
        lows = [c['low'] for c in recent]

        first_close = closes[0]
        last_close = closes[-1]
        pct_change = ((last_close - first_close) / first_close * 100) if first_close else 0

        direction = "rising" if pct_change > 0.1 else "falling" if pct_change < -0.1 else "flat"

        return (
            f"Last 5 closes: {', '.join(f'{c:.5f}' for c in closes)}. "
            f"Range: {min(lows):.5f} - {max(highs):.5f}. "
            f"Movement: {direction} ({pct_change:+.2f}%)."
        )
