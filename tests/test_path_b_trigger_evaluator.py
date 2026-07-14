from __future__ import annotations

from datetime import datetime, timedelta, timezone

from medexa.application.path_b_trigger_evaluator import PathBTriggerEvaluator
from medexa.domain.events import (
    ActivityChanged,
    BodyRegionChanged,
    ChunkProcessed,
    DocumentationGapDetected,
    NcciConflictFound,
    PathAAlertRaised,
)


def _now() -> datetime:
    return datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)


def test_body_region_keyword_fires_without_cpt():
    """Clinical Path B must not wait for CPT — keyword body region is enough."""
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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
        chunk_text="Therapist: How is your right knee feeling today?",
    )
    assert decision is not None
    assert decision.rule_id == "body_region_mentioned"
    assert "knee" in decision.reason.lower()


def test_pain_keyword_fires_before_cpt_priority():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
    events = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=2,
            suggestion_count=1,  # CPT available — clinical pain must still win
        ),
    ]
    decision = evaluator.evaluate_batch(
        events,
        now=_now(),
        chunk_text="Patient: My pain is seven out of ten in the lumbar area.",
    )
    assert decision is not None
    assert decision.rule_id in {"pain_scale_mentioned", "body_region_mentioned"}
    assert decision.rule_id != "cpt_code_detected"


def test_missing_information_keyword_triggers():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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
        chunk_text="Patient: I don't know the date of my last MRI.",
    )
    assert decision is not None
    assert decision.rule_id == "missing_information_cues"


def test_activity_changed_triggers_and_once_per_label():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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

    # Same activity label should not re-fire (once_per_match).
    again = evaluator.evaluate_batch(
        [
            ChunkProcessed(
                session_id="s1", chunk_id="c2", sequence=1, entity_count=1, suggestion_count=0
            ),
            ActivityChanged(
                session_id="s1",
                activity_label="therapeutic_exercise",
                cpt_code="97110",
                body_region="knee",
            ),
        ],
        now=_now() + timedelta(seconds=30),
    )
    assert again is None


def test_new_activity_can_trigger_after_previous_activity():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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
    decision = evaluator.evaluate_batch(second, now=base + timedelta(seconds=20))
    assert decision is not None
    assert "manual_therapy" in decision.reason


def test_body_region_changed_event_triggers():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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
    # once_per_match blocks identical region
    assert evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=30)) is None


def test_documentation_gap_triggers_once_per_cpt():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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
    assert evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=90)) is None

    other = [
        DocumentationGapDetected(
            session_id="s1",
            cpt_code="97140",
            missing_requirements=["time documented"],
            matched_phrase="manual therapy",
        ),
    ]
    assert evaluator.evaluate_batch(other, now=_now() + timedelta(seconds=25)) is not None


def test_ncci_conflict_triggers_for_medium_or_high():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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


def test_cpt_is_last_resort_not_gate():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)

    # Plain chunk with no clinical signal → no Path B
    events_no = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=0,
            suggestion_count=0,
        ),
    ]
    assert (
        evaluator.evaluate_batch(events_no, now=_now(), chunk_text="Therapist: okay next.")
        is None
    )

    # CPT-only chunk (no clinical keywords) → billing-priority CPT may fire
    events_cpt = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c2",
            sequence=1,
            entity_count=2,
            suggestion_count=1,
        ),
    ]
    decision = evaluator.evaluate_batch(
        events_cpt,
        now=_now() + timedelta(seconds=10),
        chunk_text="Starting 97110.",
    )
    assert decision is not None
    assert decision.rule_id == "cpt_code_detected"


def test_critical_respects_cooldown():
    evaluator = PathBTriggerEvaluator(interval_seconds=8, global_debounce_seconds=6)
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
    assert evaluator.evaluate_batch(events, now=base + timedelta(seconds=20)) is not None
