"""Regression: Path A chunk processing must use billing wall clock, not session_clock."""

from datetime import timedelta

from medexa.api.routers._common import billing_now, session_clock
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.schemas import SessionState
from medexa.utils.time import now_utc

engine = BillingTimerEngine()


def test_session_clock_lags_behind_billing_now_for_mature_session():
    """Simulated session clock can be minutes behind real time — must not drive billing."""
    created = now_utc() - timedelta(minutes=10)
    state = SessionState(
        session_id="s1",
        status="active",
        client_elapsed_seconds=300,
        created_at=created,
    )
    simulated = session_clock(state, 300)
    wall = billing_now(state)
    assert wall > simulated + timedelta(seconds=30)


def test_new_cpt_segment_starts_near_zero_not_client_elapsed():
    """After apply, CPT timer must not inherit client_elapsed_seconds offset."""
    state = SessionState(session_id="s1", status="active", client_elapsed_seconds=120)
    start = now_utc()
    engine.switch_segment(state, "97110", "shoulder_right", start)
    later = billing_now(state)
    elapsed = engine.running_segment_seconds(state, later)
    assert elapsed < 5
