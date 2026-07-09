from datetime import timedelta
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.schemas import SessionState
from medexa.utils.time import now_utc

engine = BillingTimerEngine()


def _fresh_state() -> SessionState:
    return SessionState(session_id="s1", status="active")


def test_accumulated_seconds_counts_running_time():
    state=_fresh_state()
    start = now_utc()
    seg = engine.start_segment(state, "97110", "shoulder_right", start)
    later = start + timedelta(seconds=90)
    assert engine.accumulated_seconds(seg, later) == 90


def test_stop_segment_freezes_time():
    state = _fresh_state()
    start = now_utc()
    seg = engine.start_segment(state, "97110", None, start)
    engine.stop_segment(state, seg.segment_id, start + timedelta(seconds=120))
    assert engine.accumulated_seconds(seg, start + timedelta(seconds=600)) == 120
    assert state.active_cpt is None


def test_switch_stops_previous_and_starts_new():
    state = _fresh_state()
    start = now_utc()
    first = engine.start_segment(state, "97110", "shoulder_right", start)
    engine.switch_segment(state, "97140", "shoulder_right", start + timedelta(seconds=300))
    assert first.stop_time is not None
    assert first.accumulated_seconds == 300
    assert state.active_cpt == "97140"
    running = [s for s in state.timer_segments if s.stop_time is None]
    assert len(running) == 1


def test_running_segment_seconds_only_counts_active_segment():
    state = _fresh_state()
    start = now_utc()
    s1 = engine.start_segment(state, "97110", None, start)
    engine.stop_segment(state, s1.segment_id, start + timedelta(seconds=600))
    engine.start_segment(state, "97140", None, start + timedelta(seconds=600))
    assert engine.seconds_by_cpt(state, start + timedelta(seconds=720)) == {
        "97110": 600,
        "97140": 120,
    }
    assert engine.running_segment_seconds(state, start + timedelta(seconds=720)) == 120
