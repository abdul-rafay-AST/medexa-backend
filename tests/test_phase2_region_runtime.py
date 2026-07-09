from __future__ import annotations

from datetime import timedelta

from medexa.api.dependencies import ServiceContainer
from medexa.schemas import SessionState, TimerSegment
from medexa.utils.time import now_utc


def test_sa_runtime_disables_eight_minute_rule() -> None:
    container = ServiceContainer()
    runtime = container.runtime_for_region("SA")
    now = now_utc()
    state = SessionState(
        session_id="sa-session",
        billing_region="SA",
        timer_segments=[
            TimerSegment(
                segment_id="seg-1",
                cpt_code="97110",
                body_region="knee_right",
                start_time=now - timedelta(minutes=40),
                stop_time=now,
                accumulated_seconds=40 * 60,
            )
        ],
    )

    summary = runtime.billing_summary_builder.build(state, now)

    assert summary.eight_minute_rule is None
    assert summary.total_units == 1


def test_sa_runtime_skips_us_ncci_conflicts() -> None:
    container = ServiceContainer()
    runtime = container.runtime_for_region("SA")
    now = now_utc()
    state = SessionState(
        session_id="sa-session",
        billing_region="SA",
        timer_segments=[
            TimerSegment(
                segment_id="seg-1",
                cpt_code="97140",
                body_region="shoulder_right",
                start_time=now - timedelta(minutes=10),
                stop_time=now,
                accumulated_seconds=10 * 60,
            ),
            TimerSegment(
                segment_id="seg-2",
                cpt_code="97110",
                body_region="shoulder_right",
                start_time=now - timedelta(minutes=10),
                stop_time=now,
                accumulated_seconds=10 * 60,
            ),
        ],
    )

    panel = runtime.insights_builder.build(state, now)

    assert panel.alerts == []
