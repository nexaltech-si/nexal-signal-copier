"""
Market Regime Detector

Detects market regime (trending/ranging/transitional) using ADX, identifies
the active trading session (Asian/European/US), and computes session-relative
volatility zones — all with pure NumPy, no external API calls.
"""
import numpy as np
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional


class MarketRegimeDetector:
    """Detect market regime, session, and volatility zone from candle data."""

    # ADX thresholds (Wilder's standard interpretation)
    TRENDING_ADX = 25
    RANGING_ADX = 20

    # Session windows in UTC
    SESSIONS = {
        "asian":     (0, 8),    # 00:00–08:00 UTC
        "european":  (7, 16),   # 07:00–16:00 UTC
        "us":        (12, 21),  # 12:00–21:00 UTC
    }

    @staticmethod
    def detect(candles: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Detect regime from candle data.

        Args:
            candles: List of OHLC dicts with 'high', 'low', 'close' keys
            now: Optional fixed datetime (for testing)

        Returns:
            {
                'regime': 'trending' | 'ranging' | 'transitional',
                'adx': float (0-100),
                'session': 'asian' | 'european' | 'us' | 'overlap_eu_us' | 'off_hours',
                'volatility_zone': 'high' | 'medium' | 'low',
            }
        """
        if not candles or len(candles) < 30:
            return {
                'regime': 'unknown',
                'adx': 0.0,
                'session': MarketRegimeDetector._detect_session(now),
                'volatility_zone': 'medium',
            }

        adx = MarketRegimeDetector._calculate_adx(candles)
        regime = MarketRegimeDetector._classify_regime(adx)
        session = MarketRegimeDetector._detect_session(now)
        vol_zone = MarketRegimeDetector._classify_volatility(candles, session)

        return {
            'regime': regime,
            'adx': round(float(adx), 2),
            'session': session,
            'volatility_zone': vol_zone,
        }

    # ── ADX (Wilder's) ────────────────────────────────────────────────────────

    @staticmethod
    def _calculate_adx(candles: list, period: int = 14) -> float:
        """
        Compute ADX using Wilder's smoothing method.

        1. TR = max(H-L, |H-C_prev|, |L-C_prev|)
        2. +DM = H - H_prev (if positive and > -DM) else 0
        3. -DM = L_prev - L (if positive and > +DM) else 0
        4. Smooth TR, +DM, -DM with Wilder's EMA (alpha=1/period)
        5. +DI = 100 * smoothed_+DM / smoothed_TR
        6. -DI = 100 * smoothed_-DM / smoothed_TR
        7. DX = 100 * |+DI - -DI| / (+DI + -DI)
        8. ADX = Wilder's EMA of DX
        """
        highs = np.array([c['high'] for c in candles])
        lows = np.array([c['low'] for c in candles])
        closes = np.array([c['close'] for c in candles])

        # True Range
        prev_close = np.roll(closes, 1)
        prev_close[0] = closes[0]
        tr = np.maximum(
            highs - lows,
            np.maximum(
                np.abs(highs - prev_close),
                np.abs(lows - prev_close)
            )
        )

        # Directional Movement
        up_move = np.diff(highs, prepend=highs[0])
        down_move = -np.diff(lows, prepend=lows[0])

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # Wilder's smoothing (alpha = 1/period, applied via cumulative sum)
        alpha = 1.0 / period

        def wilders_smooth(arr: np.ndarray) -> np.ndarray:
            """Wilder's EMA: first value is SMA, then EMA with alpha=1/period."""
            result = np.zeros_like(arr)
            result[0] = arr[0]
            for i in range(1, len(arr)):
                result[i] = result[i-1] + alpha * (arr[i] - result[i-1])
            return result

        atr = wilders_smooth(tr)
        smoothed_plus_dm = wilders_smooth(plus_dm)
        smoothed_minus_dm = wilders_smooth(minus_dm)

        # Directional Indicators
        plus_di = np.where(atr > 0, 100.0 * smoothed_plus_dm / atr, 0.0)
        minus_di = np.where(atr > 0, 100.0 * smoothed_minus_dm / atr, 0.0)

        # DX
        di_sum = plus_di + minus_di
        dx = np.where(di_sum > 0, 100.0 * np.abs(plus_di - minus_di) / di_sum, 0.0)

        # ADX = Wilder's EMA of DX
        adx = wilders_smooth(dx)

        # Return the latest ADX value
        return float(adx[-1])

    # ── Regime classification ────────────────────────────────────────────────

    @staticmethod
    def _classify_regime(adx: float) -> str:
        if adx >= MarketRegimeDetector.TRENDING_ADX:
            return 'trending'
        elif adx >= MarketRegimeDetector.RANGING_ADX:
            return 'transitional'
        return 'ranging'

    # ── Session detection ─────────────────────────────────────────────────────

    @staticmethod
    def _detect_session(now: Optional[datetime] = None) -> str:
        """
        Detect active trading session from UTC hour.

        Returns one of: asian, european, us, overlap_eu_us, off_hours
        """
        if now is None:
            now = datetime.now(timezone.utc)
        hour = now.hour

        eu = MarketRegimeDetector.SESSIONS['european']
        us = MarketRegimeDetector.SESSIONS['us']
        asian = MarketRegimeDetector.SESSIONS['asian']

        in_eu = eu[0] <= hour < eu[1]
        in_us = us[0] <= hour < us[1]
        in_asian = asian[0] <= hour < asian[1]

        if in_eu and in_us:
            return 'overlap_eu_us'
        if in_us:
            return 'us'
        if in_eu:
            return 'european'
        if in_asian:
            return 'asian'
        return 'off_hours'

    # ── Volatility zone ───────────────────────────────────────────────────────

    # Session-relative volatility thresholds (average candle range as % of price)
    SESSION_VOLATILITY = {
        'asian':         {'high': 0.40, 'low': 0.15},
        'european':      {'high': 0.70, 'low': 0.25},
        'us':            {'high': 0.80, 'low': 0.30},
        'overlap_eu_us': {'high': 0.90, 'low': 0.35},
        'off_hours':     {'high': 0.40, 'low': 0.10},
    }

    @staticmethod
    def _classify_volatility(candles: list, session: str) -> str:
        """
        Classify volatility relative to session norms.

        Uses average candle range as % of price over the last 20 candles.
        """
        ranges = np.array([c['high'] - c['low'] for c in candles[-20:]])
        prices = np.array([c['close'] for c in candles[-20:]])
        avg_range = np.mean(ranges)
        avg_price = np.mean(prices)

        if avg_price == 0:
            return 'medium'

        vol_pct = (avg_range / avg_price) * 100
        thresholds = MarketRegimeDetector.SESSION_VOLATILITY.get(
            session, {'high': 0.70, 'low': 0.20}
        )

        if vol_pct >= thresholds['high']:
            return 'high'
        elif vol_pct <= thresholds['low']:
            return 'low'
        return 'medium'
