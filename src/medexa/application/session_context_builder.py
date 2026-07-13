from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from medexa.application.session_clinical_evidence import SessionClinicalEvidenceBuilder
from medexa.schemas import SessionState, Suggestion


@dataclass(frozen=True)
class SessionFinalizeContext:
    """Immutable snapshot assembled for Path C — full session, not last chunk."""

    session_id: str
    billing_region: str
    full_transcript: str
    timeline: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    applied_suggestions: list[dict[str, Any]] = field(default_factory=list)
    assistant_hints: list[dict[str, Any]] = field(default_factory=list)
    timer_summary: list[dict[str, Any]] = field(default_factory=list)
    clinical_evidence: dict[str, Any] = field(default_factory=dict)
    patient_first_name: str = "the patient"

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "billing_region": self.billing_region,
            "full_transcript": self.full_transcript,
            "timeline": self.timeline,
            "alerts": self.alerts,
            "applied_suggestions": self.applied_suggestions,
            "assistant_hints": self.assistant_hints,
            "timer_summary": self.timer_summary,
            "clinical_evidence": self.clinical_evidence,
            "patient_first_name": self.patient_first_name,
        }


class SessionContextBuilder:
    """Builder pattern — aggregates Path A/B evidence for finalize."""

    def __init__(self, icd_loader: IcdLookupLoader | None = None) -> None:
        self._clinical_evidence_builder = SessionClinicalEvidenceBuilder(icd_loader)

    def build(self, state: SessionState) -> SessionFinalizeContext:
        transcript = self._full_transcript(state)
        clinical_evidence = self._clinical_evidence_builder.build(state, full_transcript=transcript)
        return SessionFinalizeContext(
            session_id=state.session_id,
            billing_region=state.billing_region,
            full_transcript=transcript,
            timeline=[event.model_dump(mode="json") for event in state.timeline_events],
            alerts=[alert.model_dump(mode="json") for alert in state.alerts],
            applied_suggestions=[
                self._suggestion_dict(s) for s in state.suggestions if s.status == "applied"
            ],
            assistant_hints=[
                {
                    "kind": hint.kind,
                    "title": hint.title,
                    "body": hint.body,
                }
                for hint in state.assistant_suggestions
                if hint.status == "active"
            ],
            timer_summary=self._timer_summary(state),
            clinical_evidence=clinical_evidence.to_prompt_dict(),
            patient_first_name=self._first_name(state.patient_name),
        )

    @staticmethod
    def _full_transcript(state: SessionState) -> str:
        if state.transcript_chunks:
            ordered = sorted(state.transcript_chunks, key=lambda c: c.sequence)
            joined = "\n".join(chunk.text.strip() for chunk in ordered if chunk.text.strip())
            if joined:
                return joined
        return state.transcript_text.strip()

    @staticmethod
    def _first_name(patient_name: str | None) -> str:
        if not patient_name:
            return "the patient"
        return patient_name.split(" ")[0]

    @staticmethod
    def _suggestion_dict(suggestion: Suggestion) -> dict[str, Any]:
        return {
            "title": suggestion.title,
            "cpt_code": suggestion.cpt_code,
            "body_region": suggestion.body_region,
            "status": suggestion.status,
        }

    @staticmethod
    def _timer_summary(state: SessionState) -> list[dict[str, Any]]:
        summary: list[dict[str, Any]] = []
        for segment in state.timer_segments:
            summary.append(
                {
                    "cpt_code": segment.cpt_code,
                    "body_region": segment.body_region,
                    "accumulated_seconds": segment.accumulated_seconds,
                    "is_billable": segment.is_billable,
                }
            )
        return summary
