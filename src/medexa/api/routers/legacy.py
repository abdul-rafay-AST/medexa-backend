"""Internal / back-compat endpoints.

These power the local demo script and provide lower-level controls (explicit
timers, raw insights panel, SSE stream, NCCI alert actions). They are NOT part
of the frontend ``api.ts`` contract but are stable, useful, and exercised by
``scripts/test_frontend_flow.py``.
"""

from __future__ import annotations

import uuid

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.models import (
    EndSessionResponse,
    TimerStartRequest,
    TimerSwitchRequest,
    TranscriptChunkRequest,
)
from medexa.api.routers._common import refresh_and_publish, require_state
from medexa.adapters.realtime.in_process_broker import sse_encode_stream
from medexa.logging_setup import get_logger
from medexa.schemas import TranscriptChunk
from medexa.utils.time import now_utc

router = APIRouter(prefix="/sessions", tags=["internal"])
logger = get_logger("medexa.api.legacy")


@router.post("/{session_id}/transcript-chunk")
async def ingest_transcript_chunk(
    session_id: str,
    req: TranscriptChunkRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict[str, Any]:
    started = now_utc()
    state = require_state(session_id, container)
    runtime = container.runtime_for_state(state.billing_region)
    if state.status != "active":
        raise HTTPException(status_code=409, detail="Session is not active")

    chunk = TranscriptChunk(
        session_id=session_id,
        chunk_id=str(uuid.uuid4()),
        text=req.text,
        start_ts=req.start_ts,
        end_ts=req.end_ts,
        sequence=req.sequence,
    )
    entities, new_suggestions = runtime.transcript_processor.process(state, chunk, started)
    panel = await refresh_and_publish(state, container)
    latency_ms = int((now_utc() - started).total_seconds() * 1000)
    return {
        "chunk_id": chunk.chunk_id,
        "entities_detected": len(entities),
        "suggestions": [s.model_dump() for s in new_suggestions],
        "insights": panel.model_dump(),
        "latency_ms": latency_ms,
    }


@router.get("/{session_id}/insights-panel")
async def get_insights_panel(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    state = require_state(session_id, container)
    runtime = container.runtime_for_state(state.billing_region)
    panel = runtime.insights_builder.build(state, now_utc())
    container.session_repo.save(state)
    return panel.model_dump()


@router.get("/{session_id}/billing-summary")
async def get_billing_summary(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    state = require_state(session_id, container)
    runtime = container.runtime_for_state(state.billing_region)
    return runtime.billing_summary_builder.build(state, now_utc()).model_dump()


@router.get("/{session_id}/alerts")
async def get_alerts(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    state = require_state(session_id, container)
    return {"alerts": [a.model_dump() for a in state.alerts]}


@router.post("/{session_id}/timer/start")
async def start_timer(
    session_id: str, req: TimerStartRequest, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    state = require_state(session_id, container)
    segment = container.timer_engine.start_segment(state, req.cpt_code, req.body_region, now_utc())
    await refresh_and_publish(state, container)
    return {"status": "timer_started", "segment_id": segment.segment_id, "cpt_code": req.cpt_code}


@router.post("/{session_id}/timer/stop")
async def stop_timer(
    session_id: str, segment_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    state = require_state(session_id, container)
    if not container.timer_engine.stop_segment(state, segment_id, now_utc()):
        raise HTTPException(status_code=404, detail="Running segment not found")
    await refresh_and_publish(state, container)
    return {"status": "timer_stopped", "segment_id": segment_id}


@router.post("/{session_id}/timer/switch")
async def switch_timer(
    session_id: str, req: TimerSwitchRequest, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    state = require_state(session_id, container)
    segment = container.timer_engine.switch_segment(state, req.cpt_code, req.body_region, now_utc())
    await refresh_and_publish(state, container)
    return {"status": "timer_switched", "segment_id": segment.segment_id, "cpt_code": req.cpt_code}


@router.post("/{session_id}/pause")
async def pause_session(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    state = require_state(session_id, container)
    container.timer_engine.stop_all_running(state, now_utc())
    state.status = "paused"
    await refresh_and_publish(state, container)
    return {"status": "paused", "session_id": session_id}


@router.post("/{session_id}/resume")
async def resume_session(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    state = require_state(session_id, container)
    state.status = "active"
    if state.active_cpt:
        container.timer_engine.start_segment(
            state, state.active_cpt, state.active_body_region, now_utc()
        )
    await refresh_and_publish(state, container)
    return {"status": "active", "session_id": session_id, "active_cpt": state.active_cpt}


@router.post("/{session_id}/alerts/{alert_id}/approve")
async def approve_alert(
    session_id: str, alert_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    return _set_alert_status(session_id, alert_id, "approved", container)


@router.post("/{session_id}/alerts/{alert_id}/reject")
async def reject_alert(
    session_id: str, alert_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, Any]:
    return _set_alert_status(session_id, alert_id, "rejected", container)


def _set_alert_status(
    session_id: str, alert_id: str, status: str, container: ServiceContainer
) -> dict[str, Any]:
    state = require_state(session_id, container)
    alert = next((a for a in state.alerts if a.alert_id == alert_id), None)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = status  # type: ignore[assignment]
    container.session_repo.save(state)
    return {"status": status, "alert_id": alert_id}


@router.post("/{session_id}/end", response_model=EndSessionResponse)
async def end_session(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> EndSessionResponse:
    state = require_state(session_id, container)
    now = now_utc()
    container.timer_engine.stop_all_running(state, now)
    state.status = "ended"
    runtime = container.runtime_for_state(state.billing_region)
    summary = runtime.billing_summary_builder.build(state, now)
    state.last_updated = now
    container.session_repo.save(state)
    await container.live_broker.close_channel(session_id)
    emr = summary.eight_minute_rule
    return EndSessionResponse(
        session_id=session_id,
        status="ended",
        total_minutes=summary.total_minutes,
        total_units=summary.total_units,
        units_by_cpt=emr.units_by_cpt if emr else {},
    )


@router.get("/{session_id}/stream")
async def stream_insights(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> StreamingResponse:
    require_state(session_id, container)
    return StreamingResponse(
        sse_encode_stream(session_id, container.live_broker),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
