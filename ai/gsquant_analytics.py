"""
Read-only technical/performance analytics powered by gs-quant's offline
gs_quant.timeseries module (RSI, MACD, Bollinger Bands, max drawdown,
realized volatility, returns). Sharpe ratio is computed manually from
gs-quant's offline `returns()` plus plain statistics — see note below.

This module is NOT imported by any live signal-processing or trade-execution
code path. It only ever reads candle/PnL data passed in by callers and
returns plain floats/dicts — it never writes to the database and never
touches a trading provider.

IMPORTANT, verified by hand against the actual gs-quant source (v2.0.4):
- `relative_strength_index`, `macd`, `bollinger_bands`, `max_drawdown`, and
  `returns` are confirmed fully offline — no network calls, tested with
  network access blackholed.
- `gs_quant.timeseries.econometrics.volatility` / `exponential_volatility`
  call `annualize()`, which raises if the series has more than one point on
  the same calendar date (i.e. intraday candles). We resample to daily
  closes first so this works regardless of the candle timeframe passed in.
- `gs_quant.timeseries.econometrics.sharpe_ratio` is **NOT used** here: it
  unconditionally computes excess returns via a Marquee `RiskFreeRateCurrency`
  lookup (`GsDataApi.get_market_data`), which raises `MqUninitialisedError`
  without a live `GsSession`/Marquee credentials — confirmed by reproducing
  the error locally. Sharpe is instead computed manually (annualized mean
  return over annualized volatility, risk-free rate = 0) using gs-quant's
  offline `returns()` for the return series.
"""
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger

try:
    from gs_quant.timeseries import (
        relative_strength_index,
        macd as gs_macd,
        bollinger_bands,
        max_drawdown as gs_max_drawdown,
        volatility as gs_volatility,
        returns as gs_returns,
        Window,
    )
    GS_QUANT_AVAILABLE = True
except ImportError:
    GS_QUANT_AVAILABLE = False
    logger.warning("gs-quant not available - gs-quant analytics disabled")


def _closes_from_candles(candles: List[Dict[str, Any]]) -> Optional[pd.Series]:
    """Convert the bot's candle dict format (time/open/high/low/close) into
    a close-price pandas Series indexed by timestamp, as expected by
    gs_quant.timeseries functions."""
    if not candles:
        return None

    try:
        index = pd.to_datetime([c["time"] for c in candles])
        closes = [float(c["close"]) for c in candles]
        return pd.Series(closes, index=index).sort_index()
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(f"gs-quant analytics: could not parse candles: {e}")
        return None


def get_rsi(candles: List[Dict[str, Any]], window: int = 14) -> Optional[float]:
    """Latest Relative Strength Index value, or None if unavailable."""
    if not GS_QUANT_AVAILABLE:
        return None
    closes = _closes_from_candles(candles)
    if closes is None or len(closes) < window + 1:
        return None
    try:
        series = relative_strength_index(closes, Window(window, 0))
        value = series.dropna().iloc[-1] if not series.dropna().empty else None
        return float(value) if value is not None else None
    except Exception as e:
        logger.warning(f"gs-quant RSI computation failed: {e}")
        return None


def get_macd(candles: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Latest MACD value. Returns {'macd': float} or None."""
    if not GS_QUANT_AVAILABLE:
        return None
    closes = _closes_from_candles(candles)
    if closes is None or len(closes) < 35:
        return None
    try:
        series = gs_macd(closes, 12, 26, 9)
        value = series.dropna().iloc[-1] if not series.dropna().empty else None
        return {"macd": float(value)} if value is not None else None
    except Exception as e:
        logger.warning(f"gs-quant MACD computation failed: {e}")
        return None


def get_bollinger(candles: List[Dict[str, Any]], window: int = 20, k: float = 2.0) -> Optional[Dict[str, float]]:
    """Latest Bollinger Bands (upper/middle/lower), or None if unavailable."""
    if not GS_QUANT_AVAILABLE:
        return None
    closes = _closes_from_candles(candles)
    if closes is None or len(closes) < window:
        return None
    try:
        bands = bollinger_bands(closes, Window(window, 0), k)
        latest = bands.dropna().iloc[-1] if not bands.dropna(how="all").empty else None
        if latest is None:
            return None
        return {
            "upper": float(latest.iloc[0]),
            "lower": float(latest.iloc[1]),
            "middle": float(closes.rolling(window).mean().iloc[-1]),
        }
    except Exception as e:
        logger.warning(f"gs-quant Bollinger Bands computation failed: {e}")
        return None


def get_volatility(candles: List[Dict[str, Any]], window: int = 20) -> Optional[float]:
    """Annualized realized volatility (%) of daily closes, or None.

    gs_quant's volatility()/annualize() can't infer an annualization factor
    from intraday data (raises if more than one point falls on the same
    calendar date), so we resample to one close per day first regardless of
    the candle timeframe passed in.
    """
    if not GS_QUANT_AVAILABLE:
        return None
    closes = _closes_from_candles(candles)
    if closes is None:
        return None
    daily = closes.resample("D").last().dropna()
    if len(daily) < window + 1:
        return None
    try:
        series = gs_volatility(daily, Window(window, 0))
        value = series.dropna().iloc[-1] if not series.dropna().empty else None
        return float(value) if value is not None else None
    except Exception as e:
        logger.warning(f"gs-quant volatility computation failed: {e}")
        return None


def get_indicators(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convenience bundle of all indicators for a single symbol/timeframe."""
    return {
        "rsi": get_rsi(candles),
        "macd": get_macd(candles),
        "bollinger": get_bollinger(candles),
        "volatility": get_volatility(candles),
        "available": GS_QUANT_AVAILABLE,
    }


def _equity_curve_from_pnl(pnl_by_date: Dict[str, float]) -> Optional[pd.Series]:
    """Build a cumulative-PnL equity curve Series from {date_str: pnl} pairs."""
    if not pnl_by_date:
        return None
    try:
        sorted_items = sorted(pnl_by_date.items())
        index = pd.to_datetime([d for d, _ in sorted_items])
        cumulative = pd.Series([v for _, v in sorted_items], index=index).cumsum()
        return cumulative
    except (ValueError, TypeError) as e:
        logger.warning(f"gs-quant analytics: could not build equity curve: {e}")
        return None


def get_performance_stats(pnl_by_date: Dict[str, float]) -> Dict[str, Any]:
    """
    Compute Sharpe ratio / max drawdown / volatility from a daily realized-PnL
    series (e.g. {"2026-06-01": 12.5, "2026-06-02": -4.0, ...}).

    Returns a dict with None values for any stat that can't be computed
    (e.g. too few data points) rather than raising.

    Sharpe ratio (risk-free rate = 0) is computed manually from gs-quant's
    offline `returns()` rather than `gs_quant.timeseries.sharpe_ratio`,
    which requires a live Marquee session — see module docstring.
    """
    result: Dict[str, Any] = {
        "sharpe_ratio": None,
        "max_drawdown": None,
        "volatility": None,
        "available": GS_QUANT_AVAILABLE,
    }
    if not GS_QUANT_AVAILABLE:
        return result

    equity_curve = _equity_curve_from_pnl(pnl_by_date)
    if equity_curve is None or len(equity_curve) < 2:
        return result

    try:
        rets = gs_returns(equity_curve).dropna()
        if len(rets) >= 2 and rets.std() > 0:
            annualization_factor = np.sqrt(252)
            ann_return = rets.mean() * 252
            ann_vol = rets.std() * annualization_factor
            result["sharpe_ratio"] = float(ann_return / ann_vol)
    except Exception as e:
        logger.warning(f"Sharpe ratio computation failed: {e}")

    try:
        dd = gs_max_drawdown(equity_curve)
        value = dd.dropna().iloc[-1] if not dd.dropna().empty else None
        result["max_drawdown"] = float(value) if value is not None else None
    except Exception as e:
        logger.warning(f"gs-quant max drawdown computation failed: {e}")

    try:
        daily_equity = equity_curve.resample("D").last().dropna()
        vol = gs_volatility(daily_equity) if len(daily_equity) >= 3 else None
        value = vol.dropna().iloc[-1] if vol is not None and not vol.dropna().empty else None
        result["volatility"] = float(value) if value is not None else None
    except Exception as e:
        logger.warning(f"gs-quant volatility computation failed: {e}")

    return result
