from __future__ import annotations

from datetime import datetime, timedelta, timezone

from medexa.domain.events import (
    ActivityChanged,
    BodyRegionChanged,
    ChunkProcessed,
    DocumentationGapDetected,
    NcciConflictFound,
    PathAAlertRaised,
)
from medexa.application.path_b_trigger_evaluator import PathBTriggerEvaluator


def _now() -> datetime:
    return datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def test_activity_changed_triggers_once():
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    events = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=1,
            suggestion_count=0,
        ),
        ActivityChanged(
            session_id="s1",
            activity_label="therapeutic_exercise",
            cpt_code="97110",
            body_region="knee",
        ),
    ]
    decision = evaluator.evaluate_batch(events, now=_now())
    assert decision is not None
    assert decision.source_event_type == "activity_changed"
    assert "therapeutic_exercise" in decision.reason

    # Should not re-fire within cooldown (45s).
    events_2 = [
        ChunkProcessed(session_id="s1", chunk_id="c2", sequence=1, entity_count=1, suggestion_count=0),
        ActivityChanged(session_id="s1", activity_label="therapeutic_exercise", cpt_code="97110", body_region="knee")
    ]
    again = evaluator.evaluate_batch(events_2, now=_now() + timedelta(seconds=30))
    assert again is None
    
    # Should re-fire after cooldown.
    events_3 = [
        ChunkProcessed(session_id="s1", chunk_id="c3", sequence=2, entity_count=1, suggestion_count=0),
        ActivityChanged(session_id="s1", activity_label="therapeutic_exercise", cpt_code="97110", body_region="knee")
    ]
    again_later = evaluator.evaluate_batch(events_3, now=_now() + timedelta(seconds=60))
    assert again_later is not None


def test_body_region_changed_triggers_once():
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    events = [
        BodyRegionChanged(
            session_id="s1",
            body_region="shoulder",
            matched_phrase="right shoulder",
            cpt_code="97140",
        ),
    ]
    decision = evaluator.evaluate_batch(events, now=_now())
    assert decision is not None
    assert decision.source_event_type == "body_region_changed"
    # Cooldown for body_region_transition is 45s
    assert evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=30)) is None
    assert evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=60)) is not None


def test_documentation_gap_triggers_once_per_cpt():
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    events = [
        DocumentationGapDetected(
            session_id="s1",
            cpt_code="97110",
            missing_requirements=["functional deficits documented"],
            matched_phrase="therapeutic exercise",
        ),
    ]
    decision = evaluator.evaluate_batch(events, now=_now())
    assert decision is not None
    assert decision.source_event_type == "documentation_gap_detected"
    # Cooldown for documentation_gap_first is 60s
    assert evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=30)) is None
    assert evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=90)) is not None


def test_ncci_conflict_triggers_for_medium_or_high():
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    events = [
        NcciConflictFound(
            session_id="s1",
            cpt_a="97110",
            cpt_b="97140",
            severity="medium",
        ),
    ]
    decision = evaluator.evaluate_batch(events, now=_now())
    assert decision is not None
    assert decision.source_event_type == "ncci_conflict_found"


def test_ncci_low_severity_does_not_trigger_interval_spam():
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    events = [
        NcciConflictFound(
            session_id="s1",
            cpt_a="97110",
            cpt_b="97140",
            severity="low",
        ),
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=1,
            suggestion_count=0,
        ),
    ]
    assert evaluator.evaluate_batch(events, now=_now()) is None


def test_path_a_high_alert_triggers_immediately():
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    events = [
        PathAAlertRaised(
            session_id="s1",
            alert_id="a1",
            alert_type="timer_warning",
            severity="high",
            message="timer threshold",
        ),
    ]
    decision = evaluator.evaluate_batch(events, now=_now())
    assert decision is not None
    assert decision.source_event_type == "path_a_alert_raised"


def test_cpt_detections_trigger_llm_but_plain_entities_do_not():
    """CPT suggestions trigger Path B based on declarative rules, but plain entities do not."""
    evaluator = PathBTriggerEvaluator(interval_seconds=5)
    
    # 1. Plain entities (suggestion_count=0) -> no trigger
    events_no_cpt = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=2,
            suggestion_count=0,
        ),
    ]
    assert evaluator.evaluate_batch(events_no_cpt, now=_now()) is None
    
    # 2. CPT detection (suggestion_count=1) -> triggers
    events_cpt = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c2",
            sequence=1,
            entity_count=2,
            suggestion_count=1,
        ),
    ]
    decision = evaluator.evaluate_batch(events_cpt, now=_now() + timedelta(seconds=1))
    assert decision is not None
    assert decision.rule_id == "cpt_code_detected"


def test_new_activity_can_trigger_after_previous_activity():
    evaluator = PathBTriggerEvaluator(interval_seconds=20)
    base = _now()
    first = [
        ActivityChanged(
            session_id="s1",
            activity_label="therapeutic_exercise",
            cpt_code="97110",
            body_region="knee",
        ),
    ]
    assert evaluator.evaluate_batch(first, now=base) is not None

    second = [
        ActivityChanged(
            session_id="s1",
            activity_label="manual_therapy",
            cpt_code="97140",
            body_region="knee",
        ),
    ]
    decision = evaluator.evaluate_batch(second, now=base + timedelta(seconds=60))
    assert decision is not None
    assert "manual_therapy" in decision.reason


def test_keyword_match_triggers():
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    events = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=0,
            suggestion_count=0,
        ),
    ]
    decision = evaluator.evaluate_batch(
        events,
        now=_now(),
        chunk_text="Patient says my pain level is an 8 out of 10.",
    )
    assert decision is not None
    assert decision.rule_id == "pain_scale_mentioned"

    again = evaluator.evaluate_batch(
        [
            ChunkProcessed(
                session_id="s1",
                chunk_id="c2",
                sequence=1,
                entity_count=0,
                suggestion_count=0,
            )
        ],
        now=_now() + timedelta(seconds=30),
        chunk_text="More headache pain and dizziness today.",
    )
    assert again is None


def test_critical_respects_cooldown():
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    base = _now()
    events = [
        NcciConflictFound(
            session_id="s1",
            cpt_a="97110",
            cpt_b="97140",
            severity="high",
        ),
    ]
    assert evaluator.evaluate_batch(events, now=base) is not None
    assert evaluator.evaluate_batch(events, now=base + timedelta(seconds=5)) is None
    assert evaluator.evaluate_batch(events, now=base + timedelta(seconds=31)) is not None
