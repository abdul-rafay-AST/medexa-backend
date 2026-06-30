"""Shared router helpers: session lookup, insight refresh, and recording math."""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

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
