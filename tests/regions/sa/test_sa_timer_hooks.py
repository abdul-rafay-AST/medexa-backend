"""Timer stop package tier resolution integration tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from medexa.api.mappers import _insight_id
from medexa.config import settings
from medexa.regions.registry import RegionRegistry
from medexa.regions.sa.billing.sa_timer_hooks import resolve_packages_after_stop
from medexa.regions.sa.detection.catalog import load_sa_catalog
from medexa.schemas import ProtocolInsight, SessionState, TimerSegment


@pytest.fixture(scope="module")
def sa_catalog():
    registry = RegionRegistry(settings.config_dir, settings.cpt_files_dir)
    bundle = registry.resolve("SA")
    return load_sa_catalog(bundle)


def _make_stopped_segment(cpt_code: str, accumulated_seconds: int) -> TimerSegment:
    now = datetime.now(timezone.utc)
    return TimerSegment(
        segment_id="seg-1",
        cpt_code=cpt_code,
        start_time=now - timedelta(seconds=accumulated_seconds),
        stop_time=now,
        accumulated_seconds=accumulated_seconds,
    )


def test_resolve_rewrites_parent_to_child(sa_catalog):
    seg = _make_stopped_segment("98014-00-10", 45 * 60)
    state = SessionState(session_id="t1", billing_region="SA", timer_segments=[seg])
    resolved = resolve_packages_after_stop(state, sa_catalog)
    assert resolved == ["98014-00-30"]
    assert seg.cpt_code == "98014-00-30"


def test_no_rewrite_for_non_package(sa_catalog):
    seg = _make_stopped_segment("11306-00-30", 45 * 60)
    state = SessionState(session_id="t2", billing_region="SA", timer_segments=[seg])
    resolved = resolve_packages_after_stop(state, sa_catalog)
    assert resolved == []
    assert seg.cpt_code == "11306-00-30"


def test_aggregates_multiple_segments(sa_catalog):
    """Two segments for same package family → total time determines tier."""
    seg1 = _make_stopped_segment("98014-00-10", 20 * 60)
    seg2 = _make_stopped_segment("98014-00-10", 25 * 60)
    seg2.segment_id = "seg-2"
    state = SessionState(
        session_id="t3", billing_region="SA", timer_segments=[seg1, seg2]
    )
    resolved = resolve_packages_after_stop(state, sa_catalog)
    assert resolved == ["98014-00-30"]
    assert seg1.cpt_code == "98014-00-30"
    assert seg2.cpt_code == "98014-00-30"


def test_us_session_is_no_op(sa_catalog):
    seg = _make_stopped_segment("98014-00-10", 45 * 60)
    state = SessionState(session_id="t4", billing_region="US", timer_segments=[seg])
    resolved = resolve_packages_after_stop(state, sa_catalog)
    assert resolved == []
    assert seg.cpt_code == "98014-00-10"


def test_resolve_rewrites_insight_code_and_id(sa_catalog):
    seg = _make_stopped_segment("98014-00-10", 45 * 60)
    parent_id = _insight_id("detected", "98014-00-10")
    state = SessionState(
        session_id="t5",
        billing_region="SA",
        timer_segments=[seg],
        insights=[
            ProtocolInsight(
                insight_id=parent_id,
                type="detected",
                label="Detected SBS",
                question="Bill Physiotherapy package (98014-00-10)?",
                description="Matched package parent.",
                status="pending",
                code="98014-00-10",
            )
        ],
    )
    resolved = resolve_packages_after_stop(state, sa_catalog)
    assert resolved == ["98014-00-30"]
    insight = state.insights[0]
    assert insight.code == "98014-00-30"
    assert insight.insight_id == _insight_id("detected", "98014-00-30")
    assert "98014-00-30" in insight.question
    assert insight.status == "pending"
