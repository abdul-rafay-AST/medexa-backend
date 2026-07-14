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
            suggestion_count=1,
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

    # Same activity reason must not re-fire Path B.
    again = evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=60))
    assert again is None


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
    assert evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=120)) is None


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
    assert evaluator.evaluate_batch(events, now=_now() + timedelta(seconds=120)) is None


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


def test_entity_chunks_alone_do_not_call_llm():
    """CPT/entity detections are Path A only — no Bedrock interval fallback."""
    evaluator = PathBTriggerEvaluator(interval_seconds=5)
    events = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=2,
            suggestion_count=1,
        ),
    ]
    assert evaluator.evaluate_batch(events, now=_now()) is None
    assert evaluator.evaluate_batch(
        [
            ChunkProcessed(
                session_id="s1",
                chunk_id="c2",
                sequence=1,
                entity_count=2,
                suggestion_count=1,
            )
        ],
        now=_now() + timedelta(seconds=60),
    ) is None


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
    decision = evaluator.evaluate_batch(second, now=base + timedelta(seconds=1))
    assert decision is not None
    assert "manual_therapy" in decision.reason


def test_clinical_context_triggers_once_without_entities():
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
        chunk_text="Patient reports headaches and dizziness for 3 weeks.",
    )
    assert decision is not None
    assert decision.reason == "clinical_context"

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
        now=_now() + timedelta(seconds=120),
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
