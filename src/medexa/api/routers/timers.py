"""Session and CPT timer endpoints expected by the updated frontend ``api.ts``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from medexa.api import contracts as c
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import build_timer_state, refresh_and_publish, require_state
from medexa.utils.time import now_utc

router = APIRouter(prefix="/sessions", tags=["timers"])


@router.get("/{session_id}/timer-state", response_model=c.ApiTimerState)
async def get_timer_state(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiTimerState:
    return build_timer_state(require_state(session_id, container), container)


@router.post("/{session_id}/timer-state/start", response_model=c.ApiTimerState)
async def start_session_timer(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiTimerState:
    state = require_state(session_id, container)
    state.status = "active"
    state.client_elapsed_seconds = 0
    container.session_repo.save(state)
    await refresh_and_publish(state, container)
    return build_timer_state(state, container)


@router.post("/{session_id}/timer-state/pause", response_model=c.ApiTimerState)
async def pause_session_timer(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiTimerState:
    state = require_state(session_id, container)
    container.timer_engine.stop_all_running(state, now_utc())
    state.status = "paused"
    container.session_repo.save(state)
    await refresh_and_publish(state, container)
    return build_timer_state(state, container)


@router.post("/{session_id}/timer-state/resume", response_model=c.ApiTimerState)
async def resume_session_timer(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiTimerState:
    state = require_state(session_id, container)
    state.status = "active"
    if state.active_cpt:
        container.timer_engine.start_segment(
            state, state.active_cpt, state.active_body_region, now_utc()
        )
    container.session_repo.save(state)
    await refresh_and_publish(state, container)
    return build_timer_state(state, container)


@router.post("/{session_id}/timer-state/stop", response_model=c.ApiTimerState)
async def stop_session_timer(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiTimerState:
    state = require_state(session_id, container)
    container.timer_engine.stop_all_running(state, now_utc())
    state.status = "paused"
    container.session_repo.save(state)
    await refresh_and_publish(state, container)
    return build_timer_state(state, container)


@router.post("/{session_id}/cpt-timer/start", response_model=c.ApiTimerState)
async def start_cpt_timer(
    session_id: str,
    body: c.StartCptTimerRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiTimerState:
    state = require_state(session_id, container)
    state.cpt_timer_source = body.source
    state.cpt_timer_reason = body.reason or None
    container.timer_engine.switch_segment(state, body.code, state.active_body_region, now_utc())
    container.session_repo.save(state)
    await refresh_and_publish(state, container)
    return build_timer_state(state, container)


@router.post("/{session_id}/cpt-timer/pause", response_model=c.ApiTimerState)
async def pause_cpt_timer(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiTimerState:
    state = require_state(session_id, container)
    container.timer_engine.stop_all_running(state, now_utc())
    container.session_repo.save(state)
    await refresh_and_publish(state, container)
    return build_timer_state(state, container)


@router.post("/{session_id}/cpt-timer/resume", response_model=c.ApiTimerState)
async def resume_cpt_timer(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiTimerState:
    state = require_state(session_id, container)
    if state.active_cpt:
        container.timer_engine.start_segment(
            state, state.active_cpt, state.active_body_region, now_utc()
        )
    container.session_repo.save(state)
    await refresh_and_publish(state, container)
    return build_timer_state(state, container)


@router.post("/{session_id}/cpt-timer/stop", response_model=c.ApiTimerState)
async def stop_cpt_timer(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiTimerState:
    state = require_state(session_id, container)
    container.timer_engine.stop_all_running(state, now_utc())
    state.active_cpt = None
    state.active_body_region = None
    state.cpt_timer_source = None
    state.cpt_timer_reason = None
    container.session_repo.save(state)
    await refresh_and_publish(state, container)
    return build_timer_state(state, container)
