from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.models import (
    EndSessionResponse,
    StartSessionRequest,
    StartSessionResponse,
    TimerStartRequest,
    TimerSwitchRequest,
    TranscriptChunkRequest,
)
from medexa.api.sse import sse_broker, sse_stream
from medexa.config import settings
from medexa.logging_setup import configure_logging, get_logger, new_request_id
from medexa.schemas import InsightsPanel, SessionState, TranscriptChunk
from medexa.utils.time import now_utc

configure_logging(settings.log_level)
logger = get_logger("medexa.api")

app = FastAPI(
    title="Medexa API",
    version="0.1.0",
    description="Real-time therapy session intelligence API",
)

# CORS: credentials cannot be combined with the "*" wildcard per the spec.
_allow_credentials = "*" not in settings.cors_allow_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _request_id_middleware(request, call_next):
    rid = new_request_id()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


def _require_state(session_id: str, container: ServiceContainer) -> SessionState:
    state = container.session_repo.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return state


async def _refresh_and_publish(state: SessionState, container: ServiceContainer) -> InsightsPanel:
    """Rebuild insights (mutates alerts), persist, and push over SSE."""
    now = now_utc()
    state.last_updated = now
    panel = container.insights_builder.build(state, now)
    container.session_repo.save(state)
    await sse_broker.publish(state.session_id, panel)
    return panel


@app.post("/sessions/start", response_model=StartSessionResponse)
async def start_session(
    req: StartSessionRequest,
    container: ServiceContainer = Depends(get_container),
) -> StartSessionResponse:
    session_id = str(uuid.uuid4())
    state = SessionState(
        session_id=session_id,
        patient_id=req.patient_id,
        patient_name=req.patient_name,
        mrn=req.mrn,
        therapist_id=req.therapist_id,
        session_type=req.session_type,
        status="active",
    )
    container.session_repo.save(state)
    logger.info("session_started", extra={"extra_fields": {"session_id": session_id}})
    return StartSessionResponse(
        session_id=session_id,
        status="active",
        patient_id=req.patient_id,
        patient_name=req.patient_name,
        mrn=req.mrn,
        therapist_id=req.therapist_id,
        session_type=req.session_type,
    )


@app.get("/sessions")
async def list_sessions(
    status: str | None = None,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    """Dashboard session list.

    Defaults to active sessions (the live list). Pass ``?status=all`` to include
    ended/paused sessions too (e.g. the dashboard "Recent Transactions" panel).
    """
    if status in (None, "active"):
        sessions = container.session_repo.list_active()
    else:
        sessions = container.session_repo.list_all()
        if status != "all":
            sessions = [s for s in sessions if s.status == status]
    return {"sessions": [s.model_dump() for s in sessions]}


@app.post("/sessions/{session_id}/transcript-chunk")
async def ingest_transcript_chunk(
    session_id: str,
    req: TranscriptChunkRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    started = now_utc()
    state = _require_state(session_id, container)
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

    entities, new_suggestions = container.transcript_processor.process(state, chunk, started)
    panel = await _refresh_and_publish(state, container)

    latency_ms = int((now_utc() - started).total_seconds() * 1000)
    logger.info(
        "transcript_processed",
        extra={
            "extra_fields": {
                "session_id": session_id,
                "chunk_sequence": req.sequence,
                "entities_detected": len(entities),
                "suggestions_created": len(new_suggestions),
                "latency_ms": latency_ms,
            }
        },
    )

    return {
        "chunk_id": chunk.chunk_id,
        "entities_detected": len(entities),
        "suggestions": [s.model_dump() for s in new_suggestions],
        "insights": panel.model_dump(),
        "latency_ms": latency_ms,
    }


@app.get("/sessions/{session_id}/insights")
async def get_insights(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)
    panel = container.insights_builder.build(state, now_utc())
    container.session_repo.save(state)
    return panel.model_dump()


@app.get("/sessions/{session_id}/state")
async def get_state(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    return _require_state(session_id, container).model_dump()


@app.get("/sessions/{session_id}/suggestions")
async def get_suggestions(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)
    return {"suggestions": [s.model_dump() for s in state.suggestions]}


@app.get("/sessions/{session_id}/alerts")
async def get_alerts(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)
    return {"alerts": [a.model_dump() for a in state.alerts]}


@app.get("/sessions/{session_id}/billing-summary")
async def get_billing_summary(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)
    summary = container.billing_summary_builder.build(state, now_utc())
    return summary.model_dump()


@app.post("/sessions/{session_id}/suggestions/{suggestion_id}/apply")
async def apply_suggestion(
    session_id: str,
    suggestion_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)

    suggestion = next(
        (s for s in state.suggestions if s.suggestion_id == suggestion_id), None
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status != "suggested":
        raise HTTPException(status_code=409, detail=f"Suggestion already {suggestion.status}")
    if not suggestion.cpt_code:
        raise HTTPException(status_code=400, detail="Suggestion has no CPT to apply")

    suggestion.status = "applied"
    # Applying a suggestion starts billing that CPT (mutually exclusive switch).
    container.timer_engine.switch_segment(
        state, suggestion.cpt_code, suggestion.body_region, now_utc()
    )
    panel = await _refresh_and_publish(state, container)
    return {
        "status": "applied",
        "suggestion_id": suggestion_id,
        "active_cpt": state.active_cpt,
        "insights": panel.model_dump(),
    }


@app.post("/sessions/{session_id}/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(
    session_id: str,
    suggestion_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)
    suggestion = next(
        (s for s in state.suggestions if s.suggestion_id == suggestion_id), None
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    suggestion.status = "dismissed"
    container.session_repo.save(state)
    return {"status": "dismissed", "suggestion_id": suggestion_id}


@app.post("/sessions/{session_id}/timer/start")
async def start_timer(
    session_id: str,
    req: TimerStartRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)
    segment = container.timer_engine.start_segment(
        state, req.cpt_code, req.body_region, now_utc()
    )
    await _refresh_and_publish(state, container)
    return {"status": "timer_started", "segment_id": segment.segment_id, "cpt_code": req.cpt_code}


@app.post("/sessions/{session_id}/timer/stop")
async def stop_timer(
    session_id: str,
    segment_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)
    stopped = container.timer_engine.stop_segment(state, segment_id, now_utc())
    if not stopped:
        raise HTTPException(status_code=404, detail="Running segment not found")
    await _refresh_and_publish(state, container)
    return {"status": "timer_stopped", "segment_id": segment_id}


@app.post("/sessions/{session_id}/timer/switch")
async def switch_timer(
    session_id: str,
    req: TimerSwitchRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    state = _require_state(session_id, container)
    segment = container.timer_engine.switch_segment(
        state, req.cpt_code, req.body_region, now_utc()
    )
    await _refresh_and_publish(state, container)
    return {"status": "timer_switched", "segment_id": segment.segment_id, "cpt_code": req.cpt_code}


@app.post("/sessions/{session_id}/pause")
async def pause_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    """Pause button. Stops timers but keeps the session resumable."""
    state = _require_state(session_id, container)
    container.timer_engine.stop_all_running(state, now_utc())
    state.status = "paused"
    await _refresh_and_publish(state, container)
    return {"status": "paused", "session_id": session_id}


@app.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    """Resume button. Restarts timing the CPT that was active at pause."""
    state = _require_state(session_id, container)
    state.status = "active"
    if state.active_cpt:
        container.timer_engine.start_segment(
            state, state.active_cpt, state.active_body_region, now_utc()
        )
    await _refresh_and_publish(state, container)
    return {"status": "active", "session_id": session_id, "active_cpt": state.active_cpt}


@app.post("/sessions/{session_id}/alerts/{alert_id}/approve")
async def approve_alert(
    session_id: str,
    alert_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    return _set_alert_status(session_id, alert_id, "approved", container)


@app.post("/sessions/{session_id}/alerts/{alert_id}/reject")
async def reject_alert(
    session_id: str,
    alert_id: str,
    container: ServiceContainer = Depends(get_container),
) -> dict:
    return _set_alert_status(session_id, alert_id, "rejected", container)


def _set_alert_status(
    session_id: str,
    alert_id: str,
    status: str,
    container: ServiceContainer,
) -> dict:
    state = _require_state(session_id, container)
    alert = next((a for a in state.alerts if a.alert_id == alert_id), None)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = status  # type: ignore[assignment]
    container.session_repo.save(state)
    return {"status": status, "alert_id": alert_id}


@app.post("/sessions/{session_id}/end", response_model=EndSessionResponse)
async def end_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> EndSessionResponse:
    state = _require_state(session_id, container)
    now = now_utc()
    container.timer_engine.stop_all_running(state, now)
    state.status = "ended"

    summary = container.billing_summary_builder.build(state, now)
    state.last_updated = now
    container.session_repo.save(state)
    await sse_broker.close_channel(session_id)

    logger.info(
        "session_ended",
        extra={
            "extra_fields": {
                "session_id": session_id,
                "total_minutes": summary.total_minutes,
                "total_units": summary.total_units,
            }
        },
    )

    emr = summary.eight_minute_rule
    return EndSessionResponse(
        session_id=session_id,
        status="ended",
        total_minutes=summary.total_minutes,
        total_units=summary.total_units,
        units_by_cpt=emr.units_by_cpt if emr else {},
    )


@app.get("/sessions/{session_id}/stream")
async def stream_insights(session_id: str) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/")
async def root() -> dict:
    return {"service": "medexa-api", "version": app.version, "docs": "/docs", "health": "/health"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
