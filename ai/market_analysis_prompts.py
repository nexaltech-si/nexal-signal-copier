"""
LLM prompt templates for market analysis.

Used by MarketAnalyzer's LLM-powered analysis path to provide structured
context and request structured JSON output.
"""
import json
from typing import Dict, Optional


SYSTEM_PROMPT = """You are an expert forex and gold market analyst. You receive structured market data and return a concise JSON analysis.

## Input fields you will receive:
- `symbol`: trading instrument (e.g. XAUUSD, EURUSD)
- `timeframe`: candle timeframe (e.g. 1H, 4H)
- `numerical_trend`: MA-based trend (strong_up / up / sideways / down / strong_down)
- `volatility`: market volatility level (high / medium / low)
- `momentum`: recent momentum (strong_up / up / neutral / down / strong_down)
- `trend_strength`: 0.0-1.0 confidence score from MA separation
- `regime`: ADX-based regime (trending / ranging / transitional / unknown)
- `adx`: ADX value (0-100)
- `session`: active trading session (asian / european / us / overlap_eu_us / off_hours)
- `volatility_zone`: session-relative volatility (high / medium / low)
- `recent_prices`: last 5 closing prices with brief description of movement

## Your task:
Analyze the data and return a JSON object with these fields:
- `trend`: your refined trend assessment (strong_up / up / sideways / down / strong_down)
- `confidence`: 0.0-1.0 confidence in your assessment
- `key_support`: nearest significant support level (float, use the price data)
- `key_resistance`: nearest significant resistance level (float, use the price data)
- `risk_level`: trading risk assessment (low / medium / high)
- `recommendation`: trading bias (bullish / bearish / neutral)
- `reasoning`: 1-3 sentence explanation in natural language explaining WHY

## Rules:
- If the regime is "ranging" with ADX below 20, trend assessment should favor "sideways" unless there's very strong evidence otherwise.
- If session is "off_hours" or "asian", liquidity is lower — reflect this in risk_level.
- If volatility_zone is "high", risk_level should never be "low".
- Key support/resistance must be actual price levels from the recent_prices data, not invented numbers.
- Keep reasoning concise and actionable — a trader should be able to make a decision from it.

Return ONLY valid JSON. No markdown, no code fences, no extra text."""


def build_market_analysis_prompt(
    symbol: str,
    timeframe: str,
    numerical_trend: str,
    volatility: str,
    momentum: str,
    trend_strength: float,
    regime: str,
    adx: float,
    session: str,
    volatility_zone: str,
    recent_prices: str,
) -> str:
    """Build the user prompt with structured market data for LLM analysis."""
    data = {
        "symbol": symbol,
        "timeframe": timeframe.upper(),
        "numerical_trend": numerical_trend,
        "volatility": volatility,
        "momentum": momentum,
        "trend_strength": round(trend_strength, 3),
        "regime": regime,
        "adx": round(adx, 1),
        "session": session,
        "volatility_zone": volatility_zone,
        "recent_prices": recent_prices,
    }
    return json.dumps(data, indent=2)


def parse_llm_analysis_response(response: str) -> Optional[Dict]:
    """
    Parse the LLM's JSON response. Handles markdown code fences.
    Returns the parsed dict or None on failure.
    """
    if not response:
        return None

    text = response.strip()

    # Strip markdown code fences if present
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON object with braces
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return None
