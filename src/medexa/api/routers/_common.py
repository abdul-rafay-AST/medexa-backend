"""Shared router helpers: session lookup, insight refresh, and recording math."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import HTTPException

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer
from medexa.domain.live_events import LiveEventFactory
from medexa.schemas import BillingSummary, InsightsPanel, SessionState
from medexa.utils.time import now_utc


def require_state(session_id: str, container: ServiceContainer) -> SessionState:
    state = container.session_repo.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return state


def session_clock(state: SessionState, elapsed_seconds: int) -> datetime:
    """Map session-relative elapsed seconds onto an absolute datetime for timers.

    Typed / CLI chunks advance a simulated clock instead of waiting in real time,
    so the 8-minute rule and CPT segment durations stay testable step-by-step.
    """
    return state.created_at + timedelta(seconds=max(0, int(elapsed_seconds)))


def billing_now(state: SessionState) -> datetime:
    """Clock for CPT segment accumulation.

    Live sessions (active or with a running segment) use real wall time so billing
    ticks between transcript chunks. Paused/ended sessions freeze at the simulated
    ``client_elapsed_seconds`` position for deterministic replay.
    """
    running = any(seg.stop_time is None for seg in state.timer_segments)
    if state.status == "active" or running:
        return now_utc()
    if state.client_elapsed_seconds is not None:
        return session_clock(state, int(state.client_elapsed_seconds))
    return now_utc()


async def refresh_and_publish(state: SessionState, container: ServiceContainer) -> InsightsPanel:
    now = billing_now(state)
    state.last_updated = now
    runtime = container.runtime_for_state(state.billing_region)
    panel = runtime.insights_builder.build(state, now)
    container.session_repo.save(state)
    await container.realtime.publish(
        state.session_id,
        LiveEventFactory.path_a_snapshot(
            state.session_id,
            panel,
            event_id=f"refresh-{int(now.timestamp() * 1000)}",
        ),
    )
    return panel


class RecordingMath:
    """Derived recording numbers for ``ApiRecordingState``.

    ``billing_elapsed_seconds`` sums active timer segments (billing clock).
    ``cpt_elapsed_seconds`` is the active CPT segment only.
    ``elapsed_seconds`` here reflects billing segment totals for legacy callers;
    session wall-clock is supplied separately via ``client_elapsed_seconds``.
    """

    def __init__(
        self,
        elapsed_seconds: int,
        units: int,
        seconds_to_next_unit: int,
        *,
        billing_elapsed_seconds: int,
        cpt_elapsed_seconds: int,
    ) -> None:
        self.elapsed_seconds = elapsed_seconds
        self.units = units
        self.seconds_to_next_unit = seconds_to_next_unit
        self.billing_elapsed_seconds = billing_elapsed_seconds
        self.cpt_elapsed_seconds = cpt_elapsed_seconds


def recording_math(
    summary: BillingSummary,
    *,
    billing_elapsed_seconds: int | None = None,
    cpt_elapsed_seconds: int | None = None,
) -> RecordingMath:
    elapsed = sum(item.total_seconds for item in summary.line_items)
    emr = summary.eight_minute_rule
    units = summary.total_units
    seconds_to_next = emr.seconds_to_next_unit if emr else 8 * 60
    billing = billing_elapsed_seconds if billing_elapsed_seconds is not None else elapsed
    cpt = cpt_elapsed_seconds if cpt_elapsed_seconds is not None else 0
    return RecordingMath(
        elapsed_seconds=elapsed,
        units=units,
        seconds_to_next_unit=seconds_to_next,
        billing_elapsed_seconds=billing,
        cpt_elapsed_seconds=cpt,
    )


def billing_summary(state: SessionState, container: ServiceContainer, now: datetime | None = None) -> BillingSummary:
    runtime = container.runtime_for_state(state.billing_region)
    if now is None:
        now = billing_now(state)
    return runtime.billing_summary_builder.build(state, now)


def build_timer_state(
    state: SessionState, container: ServiceContainer, now: datetime | None = None
) -> c.ApiTimerState:
    """Map domain session state to the frontend's snake_case timer contract."""
    now = now or billing_now(state)
    summary = billing_summary(state, container, now)
    math = recording_math(summary)
    total_seconds = max(math.elapsed_seconds, state.client_elapsed_seconds or 0)
    runtime = container.runtime_for_state(state.billing_region)

    cpt_seconds = container.timer_engine.running_segment_seconds(state, now)

    minutes = max(cpt_seconds // 60, 0)
    emr = None
    if runtime.profile.uses_eight_minute_rule and state.active_cpt and minutes > 0:
        emr = container.eight_minute_calculator.calculate({state.active_cpt: minutes})
    units = emr.units_by_cpt.get(state.active_cpt, 0) if emr and state.active_cpt else 0
    next_unit_at = total_seconds + (emr.seconds_to_next_unit if emr else 0)
    seconds_left = emr.seconds_to_next_unit if emr else 0

    running = any(seg.stop_time is None for seg in state.timer_segments)
    cpt_status: Literal["idle", "running", "paused", "stopped"]
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
