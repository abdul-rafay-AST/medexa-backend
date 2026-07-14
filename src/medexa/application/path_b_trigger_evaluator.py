"""Path B trigger policy — sparse, context-driven LLM calls.

Design goals:
  * Prefer Path A (rules) for every chunk; Path B only on meaningful clinical/context shifts.
  * Each non-critical reason fires at most once per session (no re-runs / loops).
  * Critical billing safety (NCCI / pre-auth) may re-fire after a cooldown.
  * Never use interval-spam fallbacks that call Bedrock on every CPT chunk.
"""

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
        "chronic",
        "acute",
        "rom",
        "range of motion",
    }
)


@dataclass(frozen=True)
class TriggerDecision:
    reason: str
    source_event_type: str
    critical: bool = False


@dataclass
class _SessionClock:
    last_critical_at: datetime | None = None
    last_chunk_sequence: int = -1
    fired_reasons: set[str] = field(default_factory=set)
    clinical_context_used: bool = False


class PathBTriggerEvaluator:
    """Decide whether a Path A event batch warrants one Bedrock Path B call."""

    def __init__(self, interval_seconds: int, *, critical_cooldown_seconds: int | None = None) -> None:
        # Re-use interval as critical cooldown floor (defaults ~20–45s).
        self._critical_cooldown = max(
            critical_cooldown_seconds if critical_cooldown_seconds is not None else interval_seconds,
            15,
        )
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

        # 1) Critical safety / billing first.
        for event in events:
            decision = self._evaluate_critical(event)
            if decision is None:
                continue
            if not self._should_fire_critical(session_id, now):
                continue
            self._mark_critical(session_id, now, decision.reason)
            return decision

        # 2) One-shot contextual transitions (activity / region / first doc-gap).
        for event in events:
            decision = self._evaluate_context(event)
            if decision is None:
                continue
            if not self._should_fire_once(session_id, decision.reason):
                continue
            self._mark_once(session_id, decision.reason)
            return decision

        # 3) Clinical narrative with no entities — at most once per session.
        chunk = next((e for e in events if isinstance(e, ChunkProcessed)), None)
        if chunk is None:
            return None
        if chunk.sequence == self._clock(session_id).last_chunk_sequence:
            return None
        self._clock(session_id).last_chunk_sequence = chunk.sequence

        if chunk.entity_count == 0 and chunk.suggestion_count == 0:
            clinical = self._evaluate_clinical_context(chunk_text)
            if clinical is None:
                return None
            clock = self._clock(session_id)
            if clock.clinical_context_used:
                return None
            clock.clinical_context_used = True
            self._mark_once(session_id, clinical.reason)
            return clinical

        # No interval fallback — CPT/entity chunks alone do not call the LLM.
        return None

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
        hits = sum(1 for keyword in _CLINICAL_KEYWORDS if keyword in lower)
        # Require denser signal than a single weak keyword ("patient").
        if hits < 2 and "pain" not in lower:
            return None
        return TriggerDecision(
            reason="clinical_context",
            source_event_type="chunk_processed",
            critical=False,
        )

    def _evaluate_critical(self, event: DomainEvent) -> TriggerDecision | None:
        if isinstance(event, NcciConflictFound) and event.severity in {"high", "medium"}:
            return TriggerDecision(
                reason=f"ncci_conflict:{event.cpt_a}+{event.cpt_b}",
                source_event_type=event.event_type,
                critical=True,
            )
        if isinstance(event, PreAuthViolationFound) and event.severity in {"high", "medium"}:
            return TriggerDecision(
                reason=f"pre_auth_violation:{event.policy_id}",
                source_event_type=event.event_type,
                critical=True,
            )
        if isinstance(event, CodeConflictFound) and event.severity in {"high", "medium"}:
            return TriggerDecision(
                reason=f"code_conflict:{event.rule_id}",
                source_event_type=event.event_type,
                critical=True,
            )
        if isinstance(event, PathAAlertRaised):
            if event.severity == "high" or event.alert_type in {
                "ncci_conflict",
                "pre_auth_required",
                "billing_conflict",
            }:
                return TriggerDecision(
                    reason=f"path_a_alert:{event.alert_type}",
                    source_event_type=event.event_type,
                    critical=True,
                )
        return None

    def _evaluate_context(self, event: DomainEvent) -> TriggerDecision | None:
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
            # First gap for a CPT only — Path A already surfaces docs requirements.
            return TriggerDecision(
                reason=f"documentation_gap:{event.cpt_code}",
                source_event_type=event.event_type,
            )
        return None

    def _should_fire_once(self, session_id: str, reason: str) -> bool:
        return reason not in self._clock(session_id).fired_reasons

    def _should_fire_critical(self, session_id: str, now: datetime) -> bool:
        clock = self._clock(session_id)
        if clock.last_critical_at is None:
            return True
        return (now - clock.last_critical_at).total_seconds() >= self._critical_cooldown

    def _mark_once(self, session_id: str, reason: str) -> None:
        self._clock(session_id).fired_reasons.add(reason)

    def _mark_critical(self, session_id: str, now: datetime, reason: str) -> None:
        clock = self._clock(session_id)
        clock.last_critical_at = now
        clock.fired_reasons.add(reason)

    def _clock(self, session_id: str) -> _SessionClock:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionClock()
        return self._sessions[session_id]

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
