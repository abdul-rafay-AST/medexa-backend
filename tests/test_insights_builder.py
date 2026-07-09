from datetime import timedelta
from pathlib import Path

from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.core.insights_builder import InsightsBuilder
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.loaders.ncci_rules_loader import NcciRulesLoader
from medexa.schemas import SessionState
from medexa.utils.time import now_utc

CONFIG = Path("config")
engine = BillingTimerEngine()
builder = InsightsBuilder(
    EightMinuteRuleCalculator(),
    NcciConflictChecker(NcciRulesLoader(CONFIG / "ncci_rules.json")),
    CptMetadataLoader(CONFIG / "cpt_metadata.json"),
    engine,
)


def test_untimed_code_excluded_from_eight_minute_rule():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    # 30 min of an untimed hot pack (97010) must NOT create time-based units.
    seg = engine.start_segment(state, "97010", None, start)
    engine.stop_segment(state, seg.segment_id, start + timedelta(minutes=30))

    panel = builder.build(state, start + timedelta(minutes=30))
    assert panel.eight_minute_rule is None  # no timed codes at all


def test_timed_code_drives_units():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    seg = engine.start_segment(state, "97110", "shoulder_right", start)
    engine.stop_segment(state, seg.segment_id, start + timedelta(minutes=20))

    panel = builder.build(state, start + timedelta(minutes=20))
    assert panel.eight_minute_rule is not None
    assert panel.eight_minute_rule.total_units == 1
    assert "97010" not in panel.eight_minute_rule.minutes_by_cpt


def test_ncci_alert_raised_for_conflicting_pair_same_region():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    s1 = engine.start_segment(state, "97110", "shoulder_right", start)
    engine.stop_segment(state, s1.segment_id, start + timedelta(minutes=10))
    s2 = engine.start_segment(state, "97140", "shoulder_right", start + timedelta(minutes=10))
    engine.stop_segment(state, s2.segment_id, start + timedelta(minutes=20))

    panel = builder.build(state, start + timedelta(minutes=20))
    assert len(panel.alerts) == 1
    assert set(panel.alerts[0].cpt_codes) == {"97110", "97140"}


def test_alert_reconciliation_preserves_decision():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    s1 = engine.start_segment(state, "97110", "shoulder_right", start)
    engine.stop_segment(state, s1.segment_id, start + timedelta(minutes=10))
    s2 = engine.start_segment(state, "97140", "shoulder_right", start + timedelta(minutes=10))
    engine.stop_segment(state, s2.segment_id, start + timedelta(minutes=20))

    builder.build(state, start + timedelta(minutes=20))
    state.alerts[0].status = "approved"
    # Rebuilding must not duplicate the alert nor reset the human decision.
    builder.build(state, start + timedelta(minutes=21))
    assert len(state.alerts) == 1
    assert state.alerts[0].status == "approved"
