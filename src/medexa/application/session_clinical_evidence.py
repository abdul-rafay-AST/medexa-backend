"""Aggregate session-level clinical + billing evidence for Path C documentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from medexa.core.clinical_transcript_extractor import TranscriptClinicalFacts, extract_transcript_clinical_facts
from medexa.loaders.icd_lookup_loader import IcdLookupLoader
from medexa.schemas import SessionState


@dataclass
class SessionClinicalEvidence:
    transcript_facts: TranscriptClinicalFacts
    detected_entities: list[dict[str, Any]] = field(default_factory=list)
    cpt_codes: list[dict[str, Any]] = field(default_factory=list)
    ncci_alerts: list[str] = field(default_factory=list)
    billing_timers: list[dict[str, Any]] = field(default_factory=list)
    compliance_gaps: list[str] = field(default_factory=list)
    assistant_hints: list[str] = field(default_factory=list)
    primary_diagnosis_code: str | None = None
    icd10_codes: list[str] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        facts = self.transcript_facts
        return {
            "pain_scales": facts.pain_scales,
            "rom_measurements": facts.rom_measurements,
            "manual_therapy_details": facts.manual_therapy_details,
            "exercise_details": facts.exercise_details,
            "intervention_blocks": [
                {
                    "category": block.category,
                    "duration_minutes": block.duration_minutes,
                    "details": block.details,
                    "cpt_code": block.cpt_code,
                }
                for block in facts.intervention_blocks
            ],
            "symptoms": facts.symptoms,
            "denies_radicular_symptoms": facts.denies_radicular,
            "diagnoses_mentioned": facts.diagnoses_mentioned,
            "hep_mentions": facts.hep_mentions,
            "mmt_documented": facts.mmt_documented,
            "session_duration_minutes": facts.session_duration_minutes,
            "detected_entities": self.detected_entities,
            "cpt_codes": self.cpt_codes,
            "ncci_alerts": self.ncci_alerts,
            "billing_timers": self.billing_timers,
            "compliance_gaps": self.compliance_gaps,
            "assistant_hints": self.assistant_hints,
            "primary_diagnosis_code": self.primary_diagnosis_code,
            "icd10_codes": self.icd10_codes,
        }


class SessionClinicalEvidenceBuilder:
    """Build authoritative structured evidence from Path A state + full transcript."""

    def __init__(self, icd_loader: IcdLookupLoader | None = None) -> None:
        self._icd_loader = icd_loader

    def build(self, state: SessionState, *, full_transcript: str) -> SessionClinicalEvidence:
        facts = extract_transcript_clinical_facts(full_transcript)
        evidence = SessionClinicalEvidence(transcript_facts=facts)

        seen_entities: set[str] = set()
        for entity in state.detected_entities:
            key = f"{entity.matched_phrase}:{entity.possible_cpt or ''}"
            if key in seen_entities:
                continue
            seen_entities.add(key)
            evidence.detected_entities.append(
                {
                    "phrase": entity.matched_phrase,
                    "body_region": entity.body_region,
                    "cpt_code": entity.possible_cpt,
                    "timing": entity.timing_phrase,
                    "billable": entity.is_billable,
                }
            )

        seen_cpt: set[str] = set()
        for suggestion in state.suggestions:
            if not suggestion.cpt_code or suggestion.cpt_code in seen_cpt:
                continue
            seen_cpt.add(suggestion.cpt_code)
            evidence.cpt_codes.append(
                {
                    "code": suggestion.cpt_code,
                    "title": suggestion.title,
                    "body_region": suggestion.body_region,
                    "status": suggestion.status,
                }
            )

        for entity in state.detected_entities:
            if entity.possible_cpt and entity.possible_cpt not in seen_cpt:
                seen_cpt.add(entity.possible_cpt)
                evidence.cpt_codes.append(
                    {
                        "code": entity.possible_cpt,
                        "title": entity.matched_phrase,
                        "body_region": entity.body_region,
                        "status": "detected",
                    }
                )

        for alert in state.alerts:
            if alert.alert_type == "ncci_conflict":
                detail = alert.message
                if "modifier 59" not in detail.lower():
                    detail = (
                        f"{detail} Consider Modifier 59 if services were distinct and "
                        "separate on the same body region."
                    )
                evidence.ncci_alerts.append(detail)

        for insight in state.insights:
            if insight.type != "billing":
                continue
            if "ncci" in insight.label.lower() or "modifier 59" in insight.description.lower():
                if insight.description not in evidence.ncci_alerts:
                    evidence.ncci_alerts.append(insight.description)

        for segment in state.timer_segments:
            minutes = max(1, round(segment.accumulated_seconds / 60))
            evidence.billing_timers.append(
                {
                    "cpt_code": segment.cpt_code,
                    "body_region": segment.body_region,
                    "minutes": minutes,
                    "seconds": segment.accumulated_seconds,
                    "billable": segment.is_billable,
                }
            )

        for gap in facts.compliance_gaps:
            if gap not in evidence.compliance_gaps:
                evidence.compliance_gaps.append(gap)

        for hint in state.assistant_suggestions:
            if hint.status != "active":
                continue
            line = f"{hint.title}: {hint.body}".strip()
            if line not in evidence.assistant_hints:
                evidence.assistant_hints.append(line)

        evidence.primary_diagnosis_code = self._resolve_primary_icd(full_transcript, state)
        if evidence.primary_diagnosis_code:
            evidence.icd10_codes = [evidence.primary_diagnosis_code]

        return evidence

    def _resolve_primary_icd(self, transcript: str, state: SessionState) -> str | None:
        lowered = transcript.lower()
        if self._icd_loader is not None:
            matches = self._icd_loader.find_matches(lowered)
            if matches:
                return matches[0][1]

        if "adhesive capsulitis" in lowered or "frozen shoulder" in lowered:
            regions = {entity.body_region for entity in state.detected_entities if entity.body_region}
            if "shoulder_right" in regions or "right shoulder" in lowered:
                return "M75.01"
            if "shoulder_left" in regions or "left shoulder" in lowered:
                return "M75.02"
            return "M75.00"
        return None
