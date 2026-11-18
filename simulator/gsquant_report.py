"""
gs-quant performance report — a post-processing step over EXISTING simulator
results, computed via gs_quant.timeseries (offline, no Marquee credentials).

This module does not change simulator/engine.py or simulator/analyzer.py, and
does not affect what the simulator replay itself does. The simulator only
replays signal *extraction* (it has no broker-fill/PnL simulation), so this
report does not fabricate price-based PnL — instead it looks up the REAL
closed-trade history already recorded in the database for the simulated
channel and runs gs-quant's Sharpe ratio / max drawdown / volatility over
that. Output is written to a separate file; the original simulation result
JSON produced by simulator/engine.py is left untouched.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from ai.gsquant_analytics import get_performance_stats


async def build_gsquant_report(results_filename: str, results_dir: str = "simulator/results") -> Optional[Path]:
    """
    Given an existing simulator results JSON filename (as already produced by
    simulator/engine.py's _save()), compute gs-quant performance stats from
    the real closed-trade history of that channel and write them to a
    sibling "<name>_gsquant_stats.json" file.

    Returns the path written, or None if the source result couldn't be read
    or no channel could be determined.
    """
    results_path = Path(results_dir)
    src_path = (results_path / results_filename).resolve()
    if not str(src_path).startswith(str(results_path.resolve())) or not src_path.exists():
        logger.warning(f"gs-quant report: source result not found: {results_filename}")
        return None

    with open(src_path, "r", encoding="utf-8") as fh:
        source = json.load(fh)

    channel_id = source.get("channel_id")
    channel_name = source.get("channel_name", "unknown")
    if channel_id is None:
        logger.warning(f"gs-quant report: no channel_id in {results_filename}")
        return None

    try:
        from src.core.database_service import db_service

        closed_trades = await db_service.db.trade.find_many(
            where={
                "status": "CLOSED",
                "profitLoss": {"not": None},
                "signal": {"is": {"channelId": str(channel_id)}},
            },
            include={"signal": True},
            order={"closedAt": "asc"},
        )
    except Exception as exc:
        logger.warning(f"gs-quant report: failed to query trade history for channel {channel_id}: {exc}")
        return None

    pnl_by_date: Dict[str, float] = defaultdict(float)
    for trade in closed_trades:
        if trade.closedAt is None or trade.profitLoss is None:
            continue
        pnl_by_date[trade.closedAt.date().isoformat()] += trade.profitLoss

    stats = get_performance_stats(dict(pnl_by_date))

    report = {
        "source_result_file": results_filename,
        "channel_id": channel_id,
        "channel_name": channel_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_count": len(closed_trades),
        "note": (
            "Computed from real closed-trade history for this channel "
            "(the simulator itself only replays signal extraction and does "
            "not simulate broker fills/PnL)."
        ),
        "stats": stats,
    }

    safe_name = re.sub(r"[^\w\-]", "_", src_path.stem)
    out_path = results_path / f"{safe_name}_gsquant_stats.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)

    logger.info(f"gs-quant report saved → {out_path}")
    return out_path
