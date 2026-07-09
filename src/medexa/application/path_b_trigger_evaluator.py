from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from medexa.domain.events import (
    ActivityChanged,
    BodyRegionChanged,
    ChunkProcessed,
    CodeConflictFound,
    DocumentationGapDetected,
    DomainEvent,
    NcciConflictFound,
    PathAAlertRaised,
    PathBTriggerRequested,
    PreAuthViolationFound,
)

_CLINICAL_KEYWORDS = frozenset(
    {
        "pain",
        "symptom",
        "symptoms",
        "complaint",
        "complaints",
        "diagnosis",
        "diagnosed",
        "medication",
        "medications",
        "allergy",
        "allergies",
        "history",
        "dizziness",
        "headache",
        "nausea",
        "fever",
        "swelling",
        "stiffness",
        "weakness",
        "numbness",
        "tingling",
        "reports",
        "patient",
        "chronic",
        "acute",
    }
)


@dataclass(frozen=True)
class TriggerDecision:
    reason: str
    source_event_type: str


@dataclass
class _SessionClock:
    last_trigger_at: datetime | None = None
    last_chunk_sequence: int = -1


class PathBTriggerEvaluator:
    _IMMEDIATE = (
        ActivityChanged,
        BodyRegionChanged,
        DocumentationGapDetected,
        NcciConflictFound,
        PathAAlertRaised,
        PreAuthViolationFound,
        CodeConflictFound,
    )

    def __init__(self, interval_seconds: int) -> None:
        self._interval_seconds = max(interval_seconds, 1)
        self._sessions: dict[str, _SessionClock] = {}

    def evaluate_batch(
        self,
        events: list[DomainEvent],
        *,
        now: datetime,
        chunk_text: str | None = None,
    ) -> TriggerDecision | None:
        if not events:
            return None
        session_id = events[0].session_id
        for event in events:
            decision = self._evaluate_immediate(event)
            if decision is not None:
                self._mark_triggered(session_id, now)
                return decision

        chunk = next((e for e in events if isinstance(e, ChunkProcessed)), None)
        if chunk is None:
            return None
        if chunk.sequence == self._clock(session_id).last_chunk_sequence:
            return None
        self._clock(session_id).last_chunk_sequence = chunk.sequence

        if chunk.entity_count == 0 and chunk.suggestion_count == 0:
            clinical = self._evaluate_clinical_context(chunk_text)
            if clinical is not None and self._interval_elapsed(session_id, now):
                self._mark_triggered(session_id, now)
                return clinical
            return None

        if not self._interval_elapsed(session_id, now):
            return None
        self._mark_triggered(session_id, now)
        return TriggerDecision(
            reason="interval_fallback",
            source_event_type="chunk_processed",
        )

    def build_trigger_event(self, session_id: str, decision: TriggerDecision) -> PathBTriggerRequested:
        return PathBTriggerRequested(
            session_id=session_id,
            trigger_id=str(uuid.uuid4()),
            reason=decision.reason,
            source_event_type=decision.source_event_type,
        )

    def _evaluate_clinical_context(self, chunk_text: str | None) -> TriggerDecision | None:
        if not chunk_text or not chunk_text.strip():
            return None
        lower = chunk_text.lower()
        if not any(keyword in lower for keyword in _CLINICAL_KEYWORDS):
            return None
        return TriggerDecision(
            reason="clinical_context",
            source_event_type="chunk_processed",
        )

    def _evaluate_immediate(self, event: DomainEvent) -> TriggerDecision | None:
        if isinstance(event, ActivityChanged):
            return TriggerDecision(
                reason=f"activity_changed:{event.activity_label}",
                source_event_type=event.event_type,
            )
        if isinstance(event, BodyRegionChanged):
            return TriggerDecision(
                reason=f"body_region_changed:{event.body_region}",
                source_event_type=event.event_type,
            )
        if isinstance(event, DocumentationGapDetected):
            return TriggerDecision(
                reason=f"documentation_gap:{event.cpt_code}",
                source_event_type=event.event_type,
            )
        if isinstance(event, NcciConflictFound):
            if event.severity in {"high", "medium"}:
                return TriggerDecision(
                    reason=f"ncci_conflict:{event.cpt_a}+{event.cpt_b}",
                    source_event_type=event.event_type,
                )
            return None
        if isinstance(event, PathAAlertRaised):
            if event.severity == "high" or event.alert_type in {
                "ncci_conflict",
                "pre_auth_required",
                "billing_conflict",
            }:
                return TriggerDecision(
                    reason=f"path_a_alert:{event.alert_type}",
                    source_event_type=event.event_type,
                )
        if isinstance(event, PreAuthViolationFound):
            if event.severity in {"high", "medium"}:
                return TriggerDecision(
                    reason=f"pre_auth_violation:{event.policy_id}",
                    source_event_type=event.event_type,
                )
        if isinstance(event, CodeConflictFound):
            if event.severity in {"high", "medium"}:
                return TriggerDecision(
                    reason=f"code_conflict:{event.rule_id}",
                    source_event_type=event.event_type,
                )
        return None

    def _clock(self, session_id: str) -> _SessionClock:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionClock()
        return self._sessions[session_id]

    def _interval_elapsed(self, session_id: str, now: datetime) -> bool:
        clock = self._clock(session_id)
        if clock.last_trigger_at is None:
            return True
        return (now - clock.last_trigger_at).total_seconds() >= self._interval_seconds

    def _mark_triggered(self, session_id: str, now: datetime) -> None:
        self._clock(session_id).last_trigger_at = now

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
