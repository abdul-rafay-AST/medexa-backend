from datetime import timedelta
from pathlib import Path

from medexa.core.billing_summary_builder import BillingSummaryBuilder
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.schemas import SessionState
from medexa.utils.time import now_utc

CONFIG = Path("config")
engine = BillingTimerEngine()
builder = BillingSummaryBuilder(
    EightMinuteRuleCalculator(),
    CptMetadataLoader(CONFIG / "cpt_metadata.json"),
    engine,
)


def test_untimed_modality_bills_one_unit():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    seg = engine.start_segment(state, "97010", None, start)
    engine.stop_segment(state, seg.segment_id, start + timedelta(minutes=30))

    summary = builder.build(state, start + timedelta(minutes=30))
    hot_pack = next(li for li in summary.line_items if li.cpt_code == "97010")
    assert hot_pack.timed is False
    assert hot_pack.units == 1
    assert summary.total_units == 1


def test_timed_plus_untimed_totals():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    s1 = engine.start_segment(state, "97110", "shoulder_right", start)
    engine.stop_segment(state, s1.segment_id, start + timedelta(minutes=20))  # 1 timed unit
    s2 = engine.start_segment(state, "97010", None, start + timedelta(minutes=20))
    engine.stop_segment(state, s2.segment_id, start + timedelta(minutes=25))  # 1 untimed unit

    summary = builder.build(state, start + timedelta(minutes=25))
    assert summary.total_units == 2
