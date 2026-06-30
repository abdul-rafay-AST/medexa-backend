from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import (
    billing_summary,
    recording_math,
    refresh_and_publish,
    require_state,
)
from medexa.logging_setup import get_logger
from medexa.schemas import PatientDisplay, SessionState
from medexa.utils.time import now_utc

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = get_logger("medexa.api.sessions")


def _recording_state(state: SessionState, container: ServiceContainer) -> c.ApiRecordingState:
    summary = billing_summary(state, container)
    math = recording_math(summary)
    return m.recording_state(
        state,
        elapsed_seconds=math.elapsed_seconds,
        units=math.units,
        seconds_to_next_unit=math.seconds_to_next_unit,
    )


@router.get("", response_model=list[c.ApiSession])
async def list_sessions(
    status: str | None = None,
    container: ServiceContainer = Depends(get_container),
) -> list[c.ApiSession]:
    """Dashboard session list. ``?status=all`` includes ended/paused sessions."""
    if status in (None, "active"):
        sessions = container.session_repo.list_active()
    else:
        sessions = container.session_repo.list_all()
        if status not in ("all", None):
            sessions = [s for s in sessions if s.status == status]
    return [m.session_to_api(s) for s in sessions]


@router.get("/{session_id}", response_model=c.ApiSession)
async def get_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiSession:
    return m.session_to_api(require_state(session_id, container))


@router.post("/start", response_model=c.StartSessionResponse)
async def start_session(
    req: c.StartSessionRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.StartSessionResponse:
    session_id = str(uuid.uuid4())
    state = SessionState(
        session_id=session_id,
        patient_id=req.patient_id or req.id,
        patient_name=req.patient_name,
        mrn=req.mrn or req.mrn_number,
        therapist_id=req.therapist_id,
        session_type=req.session_type or req.care_type,
        status="active",
        patient_display=PatientDisplay(
            avatar=req.avatar or "",
            age_sex=req.age_sex or "",
            weight=req.weight or "",
            payor_source=req.payor_source or "",
            care_type=req.care_type or "",
            cpt=req.cpt or "",
            icd=req.icd or "",
            session_time=req.session_time or "",
            date_time=req.date_time or "",
        ),
    )
    container.session_repo.save(state)
    logger.info("session_started", extra={"extra_fields": {"session_id": session_id}})
    return c.StartSessionResponse(
        session=m.session_to_api(state),
        state=_recording_state(state, container),
    )


@router.get("/{session_id}/state", response_model=c.ApiRecordingState)
async def get_state(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiRecordingState:
    return _recording_state(require_state(session_id, container), container)


@router.post("/{session_id}/state", response_model=c.ApiRecordingState)
async def update_state(
    session_id: str,
    req: c.UpdateRecordingStateRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiRecordingState:
    """Recording control via a single state-machine endpoint (the frontend's
    Pause / Resume / Stop buttons map to ``paused`` / ``recording`` / ``stopped``)."""
    state = require_state(session_id, container)
    now = now_utc()

    if req.elapsed_seconds is not None:
        state.client_elapsed_seconds = req.elapsed_seconds

    if req.status == "recording":
        # Resume: re-arm the CPT that was active when paused, if any.
        if state.status != "active":
            state.status = "active"
            if state.active_cpt:
                container.timer_engine.start_segment(
                    state, state.active_cpt, state.active_body_region, now
                )
    elif req.status == "paused":
        container.timer_engine.stop_all_running(state, now)
        state.status = "paused"
    elif req.status in ("stopped", "idle"):
        container.timer_engine.stop_all_running(state, now)
        state.status = "ended" if req.status == "stopped" else state.status

    await refresh_and_publish(state, container)
    return _recording_state(state, container)
