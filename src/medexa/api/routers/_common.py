"""Shared router helpers: session lookup, insight refresh, and recording math."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer
from medexa.api.sse import sse_broker
from medexa.schemas import BillingSummary, InsightsPanel, SessionState
from medexa.utils.time import now_utc


def require_state(session_id: str, container: ServiceContainer) -> SessionState:
    state = container.session_repo.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return state


async def refresh_and_publish(state: SessionState, container: ServiceContainer) -> InsightsPanel:
    """Rebuild the live insights panel (reconciles NCCI alerts), persist, and
    push the snapshot to any connected SSE clients."""
    now = now_utc()
    state.last_updated = now
    panel = container.insights_builder.build(state, now)
    container.session_repo.save(state)
    await sse_broker.publish(state.session_id, panel)
    return panel


class RecordingMath:
    """Derived recording numbers for ``ApiRecordingState``."""

    def __init__(self, elapsed_seconds: int, units: int, seconds_to_next_unit: int) -> None:
        self.elapsed_seconds = elapsed_seconds
        self.units = units
        self.seconds_to_next_unit = seconds_to_next_unit


def recording_math(summary: BillingSummary) -> RecordingMath:
    elapsed = sum(item.total_seconds for item in summary.line_items)
    emr = summary.eight_minute_rule
    units = summary.total_units
    seconds_to_next = emr.seconds_to_next_unit if emr else 8 * 60
    return RecordingMath(elapsed_seconds=elapsed, units=units, seconds_to_next_unit=seconds_to_next)


def billing_summary(state: SessionState, container: ServiceContainer, now: datetime | None = None) -> BillingSummary:
    return container.billing_summary_builder.build(state, now or now_utc())


def build_timer_state(
    state: SessionState, container: ServiceContainer, now: datetime | None = None
) -> c.ApiTimerState:
    """Map domain session state to the frontend's snake_case timer contract."""
    now = now or now_utc()
    summary = billing_summary(state, container, now)
    math = recording_math(summary)
    total_seconds = max(math.elapsed_seconds, state.client_elapsed_seconds or 0)

    cpt_seconds = 0
    if state.active_cpt:
        cpt_seconds = container.timer_engine.seconds_by_cpt(state, now).get(state.active_cpt, 0)

    minutes = max(cpt_seconds // 60, 0)
    emr = (
        container.eight_minute_calculator.calculate({state.active_cpt: minutes})
        if state.active_cpt and minutes > 0
        else None
    )
    units = emr.units_by_cpt.get(state.active_cpt, 0) if emr and state.active_cpt else 0
    next_unit_at = total_seconds + (emr.seconds_to_next_unit if emr else 8 * 60)
    seconds_left = emr.seconds_to_next_unit if emr else 8 * 60

    running = any(seg.stop_time is None for seg in state.timer_segments)
    if state.status == "ended":
        cpt_status = "stopped"
    elif running:
        cpt_status = "running"
    elif state.active_cpt:
        cpt_status = "paused"
    else:
        cpt_status = "idle"

    return c.ApiTimerState(
        session_id=state.session_id,
        recording_status=m.recording_status(state),
        total_seconds=total_seconds,
        cpt_timer=c.ApiCptTimerState(
            active=cpt_status == "running",
            code=state.active_cpt,
            seconds=cpt_seconds,
            units=units,
            next_unit_at_seconds=next_unit_at,
            seconds_left_to_next_unit=seconds_left,
            status=cpt_status,
            source=state.cpt_timer_source,
            reason=state.cpt_timer_reason,
        ),
    )
