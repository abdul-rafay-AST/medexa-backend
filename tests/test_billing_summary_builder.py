from datetime import timedelta
from pathlib import Path

from medexa.core.billing_engine import BillingEngine
from medexa.core.billing_summary_builder import BillingSummaryBuilder
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.loaders.ncci_rules_loader import NcciRulesLoader
from medexa.schemas import SessionState
from medexa.utils.time import now_utc

CONFIG = Path("config")
engine = BillingTimerEngine()
meta = CptMetadataLoader(CONFIG / "cpt_metadata.json")
ncci = NcciConflictChecker(NcciRulesLoader(CONFIG / "ncci_rules.json"))
billing_engine = BillingEngine(
    engine, EightMinuteRuleCalculator(), meta, ncci, use_eight_minute_rule=True
)
builder = BillingSummaryBuilder(billing_engine)


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
    engine.stop_segment(state, s1.segment_id, start + timedelta(minutes=20))
    s2 = engine.start_segment(state, "97010", None, start + timedelta(minutes=20))
    engine.stop_segment(state, s2.segment_id, start + timedelta(minutes=25))

    summary = builder.build(state, start + timedelta(minutes=25))
    assert summary.total_units == 2


def test_ncci_suppresses_bundled_code_without_approval():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    s1 = engine.start_segment(state, "97110", "shoulder_right", start)
    engine.stop_segment(state, s1.segment_id, start + timedelta(minutes=10))
    s2 = engine.start_segment(state, "97140", "shoulder_right", start + timedelta(minutes=10))
    engine.stop_segment(state, s2.segment_id, start + timedelta(minutes=20))

    state.alerts = ncci.check_conflicts(
        state.session_id, [(seg.cpt_code, seg.body_region) for seg in state.timer_segments]
    )

    summary = builder.build(state, start + timedelta(minutes=20))
    manual = next(li for li in summary.line_items if li.cpt_code == "97140")
    exercise = next(li for li in summary.line_items if li.cpt_code == "97110")
    assert manual.units == 0
    assert exercise.units >= 1


def test_ncci_allows_bundled_code_when_alert_approved():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    s1 = engine.start_segment(state, "97110", "shoulder_right", start)
    engine.stop_segment(state, s1.segment_id, start + timedelta(minutes=10))
    s2 = engine.start_segment(state, "97140", "shoulder_right", start + timedelta(minutes=10))
    engine.stop_segment(state, s2.segment_id, start + timedelta(minutes=20))

    state.alerts = ncci.check_conflicts(
        state.session_id, [(seg.cpt_code, seg.body_region) for seg in state.timer_segments]
    )
    state.alerts[0].status = "approved"

    summary = builder.build(state, start + timedelta(minutes=20))
    manual = next(li for li in summary.line_items if li.cpt_code == "97140")
    assert manual.units >= 1
