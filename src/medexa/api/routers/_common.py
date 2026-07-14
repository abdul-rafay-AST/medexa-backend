"""Shared router helpers: session lookup, insight refresh, and recording math."""

from __future__ import annotations

import asyncio
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


def reload_session_state(session_id: str, container: ServiceContainer, fallback: SessionState) -> SessionState:
    """Re-read persisted session after event handlers (e.g. Path B) may have updated it."""
    refreshed = container.session_repo.get(session_id)
    return refreshed if refreshed is not None else fallback


async def save_session_state(
    container: ServiceContainer,
    state: SessionState,
    *,
    attempts: int = 5,
) -> SessionState:
    """Persist session state with Dynamo optimistic-lock retries.

    On conflict, adopt the newer ``version`` (and Path B fields already written by
    the background worker) while keeping Path A mutations from ``state``.
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            await asyncio.to_thread(container.session_repo.save, state)
            return state
        except RuntimeError as exc:
            if "Concurrent modification" not in str(exc):
                raise
            last_error = exc
            latest = await asyncio.to_thread(container.session_repo.get, state.session_id)
            if latest is None:
                raise
            state.version = latest.version
            # Keep Path B progress written by the async worker.
            known_triggers = {t.trigger_id: t for t in state.path_b_triggers}
            for other in latest.path_b_triggers:
                existing = known_triggers.get(other.trigger_id)
                if existing is None:
                    state.path_b_triggers.append(other)
                elif other.status != existing.status:
                    existing.status = other.status
            known_suggestions = {s.suggestion_id for s in state.assistant_suggestions}
            for suggestion in latest.assistant_suggestions:
                if suggestion.suggestion_id not in known_suggestions:
                    state.assistant_suggestions.append(suggestion)
            await asyncio.sleep(0.05 * (attempt + 1))
    if last_error is not None:
        raise last_error
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
    seconds_to_next = emr.seconds_to_next_unit if emr else (8 * 60)
    billing = billing_elapsed_seconds if billing_elapsed_seconds is not None else 0
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
    runtime = container.runtime_for_state(state.billing_region)
    metrics = runtime.billing_engine.compute_metrics(state, now)
    summary = billing_summary(state, container, now)
    math = recording_math(
        summary,
        billing_elapsed_seconds=metrics.timed_pool_seconds,
        cpt_elapsed_seconds=metrics.running_segment_seconds,
    )
    wall = int(state.client_elapsed_seconds or 0)

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
        total_seconds=wall,
        cpt_timer=c.ApiCptTimerState(
            active=cpt_status == "running",
            code=state.active_cpt,
            seconds=metrics.running_segment_seconds,
            units=math.units,
            next_unit_at_seconds=math.billing_elapsed_seconds + math.seconds_to_next_unit,
            seconds_left_to_next_unit=math.seconds_to_next_unit,
            status=cpt_status,
            source=state.cpt_timer_source,
            reason=state.cpt_timer_reason,
        ),
    )
