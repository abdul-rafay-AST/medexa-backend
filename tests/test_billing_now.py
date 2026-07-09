from datetime import timedelta

from medexa.api.routers._common import billing_now, session_clock
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.schemas import SessionState
from medexa.utils.time import now_utc

engine = BillingTimerEngine()


def test_billing_now_uses_wall_clock_when_active():
    state = SessionState(session_id="s1", status="active", client_elapsed_seconds=30)
    before = now_utc()
    assert billing_now(state) >= before


def test_billing_now_freezes_when_paused():
    state = SessionState(session_id="s1", status="paused", client_elapsed_seconds=120)
    frozen = session_clock(state, 120)
    assert billing_now(state) == frozen


def test_running_segment_advances_without_client_elapsed_update():
    """Billing must tick in real time between transcript chunks."""
    state = SessionState(session_id="s1", status="active", client_elapsed_seconds=10)
    start = now_utc()
    engine.start_segment(state, "97110", "shoulder_right", start)
    later = billing_now(state)
    assert engine.running_segment_seconds(state, later) >= 0
    # Segment started at wall time; a later billing_now should not be before start.
    assert later >= start


def test_billing_now_follows_running_segment_when_paused_status():
    """Apply can start a segment while status is still paused — clock must run."""
    state = SessionState(session_id="s1", status="paused", client_elapsed_seconds=60)
    start = now_utc()
    engine.start_segment(state, "97110", None, start)
    assert billing_now(state) >= start
