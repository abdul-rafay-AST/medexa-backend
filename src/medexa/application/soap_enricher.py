"""Merge Path A structured evidence into SOAP drafts — prevents over-summarization."""

from __future__ import annotations

from medexa.application.session_clinical_evidence import SessionClinicalEvidence
from medexa.schemas import (
    SessionState,
    SoapAssessment,
    SoapBillingDocumentation,
    SoapNote,
    SoapObjective,
    SoapPlan,
    SoapSubjective,
)


class SoapEnricher:
    """Deterministic post-processor for Path C SOAP output."""

    def enrich(
        self,
        soap: SoapNote,
        evidence: SessionClinicalEvidence,
        state: SessionState,
    ) -> SoapNote:
        facts = evidence.transcript_facts
        subjective = self._enrich_subjective(soap.subjective, facts, state)
        objective = self._enrich_objective(soap.objective, evidence)
        assessment = self._enrich_assessment(soap.assessment, evidence, facts)
        plan = self._enrich_plan(soap.plan, evidence, facts)
        billing_documentation = self._build_billing_documentation(evidence)

        return SoapNote(
            subjective=subjective,
            objective=objective,
            assessment=assessment,
            plan=plan,
            billing_documentation=billing_documentation,
            generated=soap.generated,
        )

    def _enrich_subjective(
        self,
        subjective: SoapSubjective,
        facts,
        state: SessionState,
    ) -> SoapSubjective:
        complaint = subjective.chief_complaint.strip()
        if not complaint and state.transcript_text:
            complaint = state.transcript_text[:320]

        symptom_text = ", ".join(facts.symptoms)
        if symptom_text and symptom_text.lower() not in complaint.lower():
            complaint = f"{complaint} Symptoms include {symptom_text}.".strip()

        if facts.denies_radicular and "radicular" not in complaint.lower():
            complaint = f"{complaint} Denies radicular symptoms/tingling.".strip()

        pain_scale = subjective.pain_scale.strip() or ", ".join(facts.pain_scales)
        return SoapSubjective(
            chief_complaint=complaint,
            pain_scale=pain_scale,
            duration=subjective.duration,
        )

    def _enrich_objective(self, objective: SoapObjective, evidence: SessionClinicalEvidence) -> SoapObjective:
        facts = evidence.transcript_facts
        rom = objective.range_of_motion.strip()
        if facts.rom_measurements:
            extracted = "; ".join(facts.rom_measurements)
            rom = extracted if not rom else f"{rom}; {extracted}"

        intervention_lines: list[str] = []
        for block in facts.intervention_blocks:
            duration = f"{block.duration_minutes} min" if block.duration_minutes else "duration not stated"
            cpt = f" ({block.cpt_code})" if block.cpt_code else ""
            intervention_lines.append(f"{block.category}{cpt}: {duration} — {block.details}")

        if facts.session_duration_minutes:
            intervention_lines.append(f"Total skilled intervention time: ~{facts.session_duration_minutes} minutes.")

        observation = objective.observation_notes.strip()
        if intervention_lines:
            block_text = " | ".join(intervention_lines)
            if not self._contains_intervention_keywords(observation):
                observation = f"{observation} Interventions: {block_text}.".strip()
            elif block_text.lower() not in observation.lower():
                observation = f"{observation} {block_text}.".strip()

        if facts.mmt_documented and "mmt" not in observation.lower():
            observation = f"{observation} Manual muscle testing documented.".strip()

        return SoapObjective(
            observation_notes=observation,
            range_of_motion=rom,
            affect=objective.affect,
            vital_signs=objective.vital_signs,
        )

    def _enrich_assessment(
        self,
        assessment: SoapAssessment,
        evidence: SessionClinicalEvidence,
        facts,
    ) -> SoapAssessment:
        summary = assessment.diagnosis_summary.strip()
        if facts.diagnoses_mentioned:
            dx = "; ".join(facts.diagnoses_mentioned)
            if dx.lower() not in summary.lower():
                summary = f"{summary} Clinical focus: {dx}.".strip()

        gap_text = "; ".join(evidence.compliance_gaps)
        if gap_text and gap_text.lower() not in summary.lower():
            summary = f"{summary} Documentation gaps to address: {gap_text}.".strip()

        return SoapAssessment(
            diagnosis_summary=summary or "Clinician to confirm assessment.",
            primary_diagnosis_code=assessment.primary_diagnosis_code,
            severity=assessment.severity or "Moderate",
        )

    def _enrich_plan(self, plan: SoapPlan, evidence: SessionClinicalEvidence, facts) -> SoapPlan:
        follow_up = plan.follow_up_plan.strip() or "Continue skilled physical therapy per plan of care."
        if facts.hep_mentions:
            hep = ", ".join(facts.hep_mentions)
            if hep.lower() not in follow_up.lower():
                follow_up = f"{follow_up} HEP: continue {hep}.".strip()

        if evidence.ncci_alerts:
            ncci = evidence.ncci_alerts[0]
            if ncci.lower() not in follow_up.lower():
                follow_up = f"{follow_up} Billing note: {ncci}".strip()

        return SoapPlan(follow_up_plan=follow_up)

    def _build_billing_documentation(self, evidence: SessionClinicalEvidence) -> SoapBillingDocumentation:
        intervention_blocks: list[str] = []
        for block in evidence.transcript_facts.intervention_blocks:
            duration = f"{block.duration_minutes} min" if block.duration_minutes else "duration per transcript"
            code = block.cpt_code or "unmapped"
            intervention_blocks.append(f"{code} {block.category}: {duration} — {block.details}")

        for timer in evidence.billing_timers:
            line = (
                f"{timer['cpt_code']} timer: {timer['minutes']} min "
                f"({timer['seconds']}s) region={timer.get('body_region') or 'unspecified'}"
            )
            if line not in intervention_blocks:
                intervention_blocks.append(line)

        cpt_summary = [
            f"{item['code']} — {item.get('title', '')} ({item.get('status', 'detected')})"
            for item in evidence.cpt_codes
        ]

        return SoapBillingDocumentation(
            intervention_blocks=intervention_blocks,
            cpt_summary=cpt_summary,
            ncci_alerts=list(evidence.ncci_alerts),
            compliance_gaps=list(evidence.compliance_gaps),
            total_session_minutes=evidence.transcript_facts.session_duration_minutes,
        )

    @staticmethod
    def _contains_intervention_keywords(text: str) -> bool:
        lowered = text.lower()
        return any(
            token in lowered
            for token in (
                "manual therapy",
                "mobilization",
                "therapeutic exercise",
                "isometric",
                "wall walk",
                "97140",
                "97110",
            )
        )
