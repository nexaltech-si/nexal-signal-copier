"""
gs-quant analytics router — read-only technical indicator and performance
endpoints powered by gs_quant.timeseries (offline, no Marquee credentials).

This router only reads candle data (via the existing trading provider's
get_historical_candles, the same read-only call already used by
ai/market_analyzer.py) and trade history (via Prisma). It never writes
anything and never participates in signal processing or order execution.

Mount this router in api_server.py with:
    from src.api.gsquant_routes import gsquant_router
    app.include_router(gsquant_router)
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from ai.gsquant_analytics import get_indicators, get_performance_stats
from simulator.gsquant_report import build_gsquant_report


gsquant_router = APIRouter(prefix="/api/gsquant", tags=["gsquant"])


@gsquant_router.get("/indicators/{symbol}")
async def get_symbol_indicators(
    symbol: str,
    timeframe: str = Query("1h", description="Candle timeframe, e.g. 15m, 1h, 4h"),
    limit: int = Query(200, ge=50, le=1000),
) -> Dict[str, Any]:
    """RSI / MACD / Bollinger Bands / volatility for a symbol, computed via
    gs-quant's offline timeseries functions over recently cached candles."""
    try:
        from src.services.trading_service import trading_service

        provider = trading_service.trading_provider
        if not provider or not getattr(provider, "is_connected", False):
            return {"ok": False, "error": "Trading provider not connected", "symbol": symbol}

        candles = await provider.get_historical_candles(symbol=symbol, timeframe=timeframe, limit=limit)
        if not candles:
            return {"ok": False, "error": "No candle data available", "symbol": symbol}

        indicators = get_indicators(candles)
        return {"ok": True, "symbol": symbol, "timeframe": timeframe, "indicators": indicators}
    except Exception as exc:
        logger.warning(f"gs-quant indicators endpoint failed for {symbol}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@gsquant_router.get("/performance")
async def get_performance(days: int = Query(90, ge=1, le=3650)) -> Dict[str, Any]:
    """Sharpe ratio / max drawdown / volatility computed via gs-quant from
    real closed-trade PnL history, grouped by day."""
    try:
        from datetime import datetime, timedelta, timezone
        from src.core.database_service import db_service

        date_from = datetime.now(timezone.utc) - timedelta(days=days)
        closed_trades = await db_service.db.trade.find_many(
            where={
                "status": "CLOSED",
                "closedAt": {"gte": date_from},
                "profitLoss": {"not": None},
            },
            order={"closedAt": "asc"},
        )

        if not closed_trades:
            return {"ok": True, "trade_count": 0, "stats": get_performance_stats({})}

        pnl_by_date: Dict[str, float] = defaultdict(float)
        for trade in closed_trades:
            if trade.closedAt is None or trade.profitLoss is None:
                continue
            day_key = trade.closedAt.date().isoformat()
            pnl_by_date[day_key] += trade.profitLoss

        stats = get_performance_stats(dict(pnl_by_date))
        return {"ok": True, "trade_count": len(closed_trades), "days": days, "stats": stats}
    except Exception as exc:
        logger.warning(f"gs-quant performance endpoint failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@gsquant_router.post("/simulator-report/{results_filename}")
async def generate_simulator_report(results_filename: str) -> Dict[str, Any]:
    """Generate a gs-quant Sharpe/drawdown/volatility report for an existing
    simulator results file, based on that channel's real closed-trade
    history. Writes a sibling "*_gsquant_stats.json" file; the original
    simulator result file is never modified."""
    try:
        out_path = await build_gsquant_report(results_filename)
        if out_path is None:
            raise HTTPException(status_code=404, detail="Could not generate report for this result file.")
        return {"ok": True, "report_file": out_path.name}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(f"gs-quant simulator report generation failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@gsquant_router.get("/simulator-report/{report_filename}")
async def get_simulator_report(report_filename: str) -> Dict[str, Any]:
    """Fetch a previously generated gs-quant simulator report by filename."""
    from pathlib import Path

    results_dir = Path("simulator/results")
    path = (results_dir / report_filename).resolve()
    if not str(path).startswith(str(results_dir.resolve())) or not path.exists():
        raise HTTPException(status_code=404, detail="Report file not found.")

    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {"ok": True, "data": data}
