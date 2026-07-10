from datetime import timedelta
from pathlib import Path

from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.suggestion_generator import SuggestionGenerator
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.schemas import DetectedEntity, SessionState
from medexa.utils.time import now_utc

gen = SuggestionGenerator(
    CptMetadataLoader(Path("config/cpt_metadata.json")), cooldown_seconds=120
)
engine = BillingTimerEngine()


def _entity(cpt: str = "97140", region: str | None = "shoulder_right") -> DetectedEntity:
    return DetectedEntity(
        activity_label="manual_therapy",
        matched_phrase="soft tissue work",
        body_region=region,
        is_billable=True,
        possible_cpt=cpt,
        source_chunk_id="c1",
    )


def test_billable_entity_creates_suggestion():
    out = gen.generate("s1", [_entity()], existing=[], now=now_utc())
    assert len(out) == 1
    assert out[0].cpt_code == "97140"
    assert out[0].suggestion_type == "cpt_apply"


def test_non_billable_entity_skipped():
    e = _entity()
    e.is_billable = False
    assert gen.generate("s1", [e], existing=[], now=now_utc()) == []


def test_dedupe_within_same_batch():
    out = gen.generate("s1", [_entity(), _entity()], existing=[], now=now_utc())
    assert len(out) == 1


def test_dedupe_against_existing_within_cooldown():
    now = now_utc()
    first = gen.generate("s1", [_entity()], existing=[], now=now)
    second = gen.generate("s1", [_entity()], existing=first, now=now + timedelta(seconds=10))
    assert second == []


def test_suggested_blocks_resuggest_permanently():
    now = now_utc()
    first = gen.generate("s1", [_entity()], existing=[], now=now)
    later = gen.generate("s1", [_entity()], existing=first, now=now + timedelta(seconds=200))
    assert later == []


def test_dismissed_allows_resuggest():
    now = now_utc()
    first = gen.generate("s1", [_entity()], existing=[], now=now)
    first[0].status = "dismissed"
    later = gen.generate("s1", [_entity()], existing=first, now=now + timedelta(seconds=10))
    assert len(later) == 1


def test_applied_suggestion_blocks_resuggest():
    now = now_utc()
    first = gen.generate("s1", [_entity()], existing=[], now=now)
    first[0].status = "applied"
    later = gen.generate("s1", [_entity()], existing=first, now=now + timedelta(seconds=999))
    assert later == []


def test_new_cpt_suggested_while_another_is_actively_billing():
    now = now_utc()
    state = SessionState(session_id="s1", status="active")
    engine.start_segment(state, "97110", "spine_lumbar", now)
    active = [("97110", "spine_lumbar")]
    first = gen.generate("s1", [_entity("97110", "spine_lumbar")], existing=[], now=now, active_segments=active)
    assert first == []
    second = gen.generate(
        "s1",
        [_entity("97140", "spine_lumbar")],
        existing=[],
        now=now,
        active_segments=active,
    )
    assert len(second) == 1
    assert second[0].cpt_code == "97140"


def test_switch_segment_resets_running_timer_keeps_prior_units():
    state = SessionState(session_id="s1", status="active")
    start = now_utc()
    engine.start_segment(state, "97110", None, start)
    engine.switch_segment(state, "97140", None, start + timedelta(seconds=300))
    assert engine.running_segment_seconds(state, start + timedelta(seconds=310)) == 10
    assert engine.seconds_by_cpt(state, start + timedelta(seconds=310))["97110"] == 300
