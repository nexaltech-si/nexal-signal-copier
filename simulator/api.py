"""
Simulator FastAPI router — REST + SSE endpoints.

Mount this router in api_server.py with:
    from simulator.api import simulator_router
    app.include_router(simulator_router)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional, Union

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from loguru import logger

from simulator.service import simulator_service, SimStatus


simulator_router = APIRouter(prefix="/api/simulator", tags=["simulator"])


# ── Request models ────────────────────────────────────────────────────────────

def _source_and_id(source: Optional[str], channel_id: Union[int, str]):
    """("telegram" | "discord", int id). Discord ids arrive as text: they are too
    large for a JavaScript number."""
    try:
        return ("discord" if (source or "").lower() == "discord" else "telegram"), int(str(channel_id).strip())
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid channel id.")


def _discord_channels() -> list:
    try:
        from src.integrations.discord.listener import discord_listener
        return [{"id": c["id"], "name": c["name"], "label": c["label"], "group": f"Discord · {c['group']}",
                 "username": None, "type": "discord", "source": "discord"}
                for c in discord_listener.replay_channels()]
    except Exception as exc:
        logger.warning(f"Could not list Discord channels for the simulator: {exc}")
        return []


class RunSimulationRequest(BaseModel):
    channel_id: Union[int, str]
    source: Optional[str] = None
    channel_name: str
    start_date: str
    end_date: str
    limit: int = 1000
    enable_brain: bool = False


# ── Channels ──────────────────────────────────────────────────────────────────

@simulator_router.get("/channels")
async def get_channels() -> Dict[str, Any]:
    """Telegram channels from the live bot's dialogs cache, plus the Discord channels
    selected on the Discord page. Either source may be missing."""
    channels = []
    error = None
    try:
        from src.services.telegram_channel_service_prisma import telegram_channel_service_prisma
        raw = await telegram_channel_service_prisma.get_all_channels_from_cache()
        for item in raw.get("channels", []) + raw.get("supergroups", []):
            channels.append({
                "id": int(item["id"]),
                "name": item.get("title") or item.get("username") or item["id"],
                "username": item.get("username"),
                "type": "channel" if item.get("broadcast") else "group",
                "source": "telegram",
            })
    except Exception as exc:
        logger.warning(f"Could not fetch Telegram channels for simulator: {exc}")
        error = str(exc)
    channels.sort(key=lambda c: str(c["name"]).lower())
    channels.extend(sorted(_discord_channels(), key=lambda c: c["name"].lower()))   # after Telegram, group by group
    if not channels and error:
        return {"ok": False, "channels": [], "error": error}
    return {"ok": True, "channels": channels}


# ── Status / run / stop ───────────────────────────────────────────────────────

@simulator_router.get("/status")
async def get_status() -> Dict[str, Any]:
    return simulator_service.get_status_dict()


@simulator_router.post("/run")
async def run_simulation(req: RunSimulationRequest) -> Dict[str, Any]:
    if simulator_service.status == SimStatus.RUNNING:
        raise HTTPException(status_code=409, detail="A simulation is already running.")

    try:
        start_dt = datetime.fromisoformat(req.start_date)
        end_dt = datetime.fromisoformat(req.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")

    if start_dt >= end_dt:
        raise HTTPException(status_code=422, detail="start_date must be before end_date.")

    source, channel_id = _source_and_id(req.source, req.channel_id)
    await simulator_service.start_simulation(
        source=source,
        channel_id=channel_id,
        channel_name=req.channel_name,
        start_date=start_dt,
        end_date=end_dt,
        limit=max(1, min(req.limit, 10_000)),
        enable_brain=req.enable_brain,
    )
    return {"ok": True, "message": f"Simulation started for {req.channel_name!r}"}


@simulator_router.post("/stop")
async def stop_simulation() -> Dict[str, Any]:
    if simulator_service.status != SimStatus.RUNNING:
        raise HTTPException(status_code=409, detail="No simulation is currently running.")
    simulator_service.stop_simulation()
    return {"ok": True, "message": "Simulation cancellation requested."}


# ── Results ───────────────────────────────────────────────────────────────────

@simulator_router.get("/results")
async def list_results() -> Dict[str, Any]:
    return {"ok": True, "results": simulator_service.list_results()}


@simulator_router.get("/results/{filename}")
async def get_result(filename: str) -> Dict[str, Any]:
    try:
        data = simulator_service.get_result(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if data is None:
        raise HTTPException(status_code=404, detail="Result file not found.")
    return {"ok": True, "data": data}


@simulator_router.delete("/results/{filename}")
async def delete_result(filename: str) -> Dict[str, Any]:
    try:
        deleted = simulator_service.delete_result(filename)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not deleted:
        raise HTTPException(status_code=404, detail="Result file not found.")
    return {"ok": True, "message": f"Deleted {filename}"}


# ── SSE event stream ──────────────────────────────────────────────────────────

@simulator_router.get("/events")
async def event_stream() -> StreamingResponse:
    """
    Server-Sent Events stream of real-time simulation progress.
    Proxied through Next.js — the frontend never connects here directly.

    Event types:
      status_snapshot     — sent immediately on connect
      simulation_started  — new run kicked off
      message_processed   — one message done (current, total, trade summary)
      simulation_complete — run finished (summary)
      simulation_cancelled
      simulation_error    — error string
      ping                — keepalive every 20 s
    """
    return StreamingResponse(
        _sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_generator() -> AsyncGenerator[str, None]:
    q = simulator_service.subscribe()
    try:
        # Send current state immediately so the client has context on connect
        snapshot = {"type": "status_snapshot", **simulator_service.get_status_dict()}
        yield _sse(snapshot)

        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=20.0)
                yield _sse(event)
            except asyncio.TimeoutError:
                yield _sse({"type": "ping"})
    except asyncio.CancelledError:
        pass
    finally:
        simulator_service.unsubscribe(q)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ── Flow replay: real channel messages through the real bot, simulated broker ──

class FlowReplayRequest(BaseModel):
    channel_id: Union[int, str]
    source: Optional[str] = None
    channel_name: str
    start_date: str
    end_date: str
    limit: int = 300
    runner: bool | None = None            # None = as configured for the live bot
    runner_share_percent: float | None = None
    risk_percent: float | None = None


@simulator_router.post("/flow/run")
async def flow_run(req: FlowReplayRequest) -> Dict[str, Any]:
    from simulator.flow_replay import flow_replay_service
    try:
        start_dt = datetime.fromisoformat(req.start_date)
        end_dt = datetime.fromisoformat(req.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")
    if start_dt >= end_dt:
        raise HTTPException(status_code=422, detail="The start must be before the end.")
    overrides: Dict[str, Any] = {}
    if req.runner is not None:
        overrides["enable_runner_split"] = req.runner
    if req.runner_share_percent is not None:
        overrides["runner_share_percent"] = max(0.0, min(float(req.runner_share_percent), 100.0))
    if req.risk_percent is not None:
        overrides["max_risk_per_trade_percent"] = max(0.01, min(float(req.risk_percent), 10.0))
    source, channel_id = _source_and_id(req.source, req.channel_id)
    try:
        await flow_replay_service.start(channel_id, req.channel_name, start_dt, end_dt,
                                        max(1, min(req.limit, 2000)), overrides, source=source)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True}


@simulator_router.get("/flow/state")
async def flow_state(since: int = 0) -> Dict[str, Any]:
    """Status plus the events from index `since` on (the page polls this)."""
    from simulator.flow_replay import flow_replay_service
    return flow_replay_service.state(since)


@simulator_router.post("/flow/stop")
async def flow_stop() -> Dict[str, Any]:
    from simulator.flow_replay import flow_replay_service
    flow_replay_service.stop()
    return {"ok": True}
