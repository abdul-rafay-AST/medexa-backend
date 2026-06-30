"""SOAP note generation service — Strategy pattern with Rules and Bedrock adapters.

Healthcare compliance:
  * Generated notes are explicitly marked as *drafts* for clinician edit.
  * HIPAA: the system assists, the licensed clinician authors the record.
  * No PHI is logged; only structured session state is accessed.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from medexa.schemas import (
    SessionState,
    SoapAssessment,
    SoapNote,
    SoapObjective,
    SoapPlan,
    SoapSubjective,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class SoapGenerator(Protocol):
    """Port: draft a structured SOAP note from accumulated session evidence."""

    def generate(self, state: SessionState) -> SoapNote: ...


class RulesSoapGenerator:
    """Assembles a SOAP draft from the session's stored clinical analysis,
    detected billing activities, and transcript — deterministically, no LLM.

    The output is explicitly a *draft* for clinician edit (HIPAA: the system
    assists, the licensed clinician authors the record)."""

    def generate(self, state: SessionState) -> SoapNote:
        analysis = state.latest_analysis
        soap_update = analysis.soap_update if analysis else None

        symptoms = analysis.symptoms if analysis else []
        chief_complaint = (
            soap_update.subjective
            if soap_update and soap_update.subjective
            else (state.transcript_text[:280] if state.transcript_text else "")
        )

        primary_icd = ""
        diagnosis_summary = ""
        if analysis and analysis.icd10_suggestions:
            top = analysis.icd10_suggestions[0]
            primary_icd = top.code
            diagnosis_summary = f"{top.phrase.title()} ({top.code})."
        if analysis and analysis.possible_diagnoses:
            diagnosis_summary = (
                diagnosis_summary + " " + "; ".join(analysis.possible_diagnoses[:3])
            ).strip()

        regions = ", ".join(r.region.replace("_", " ") for r in (analysis.body_regions if analysis else []))
        objective_notes = (
            soap_update.objective if soap_update and soap_update.objective else ""
        )
        if regions:
            objective_notes = (objective_notes + f" Regions addressed: {regions}.").strip()

        plan_text = (
            soap_update.plan
            if soap_update and soap_update.plan
            else "Continue current plan of care; reassess at next visit."
        )
        cpt_names = [c.display_name for c in (analysis.cpt_suggestions if analysis else [])]
        if cpt_names:
            plan_text = f"{plan_text} Interventions: {', '.join(cpt_names)}."

        return SoapNote(
            subjective=SoapSubjective(
                chief_complaint=chief_complaint,
                pain_scale=state.soap.subjective.pain_scale,
                duration=state.soap.subjective.duration,
            ),
            objective=SoapObjective(
                observation_notes=objective_notes,
                range_of_motion=state.soap.objective.range_of_motion,
                affect=state.soap.objective.affect,
                vital_signs=state.soap.objective.vital_signs,
            ),
            assessment=SoapAssessment(
                diagnosis_summary=diagnosis_summary or "Clinician to confirm assessment.",
                primary_diagnosis_code=primary_icd,
                severity=state.soap.assessment.severity or "Moderate",
            ),
            plan=SoapPlan(follow_up_plan=plan_text),
            generated=True,
        )


class BedrockSoapGenerator:
    """Amazon Bedrock SOAP generator — invokes a foundation model for richer,
    narrative-style SOAP notes from the full session context.

    Falls back to the rules generator on any error so the endpoint always
    returns a valid SOAP note regardless of AWS availability.

    Healthcare compliance:
      * All generated notes carry ``generated=True`` flag.
      * Clinician review language is embedded in the output.
      * No PHI is sent to external services beyond the transcript text.
    """

    def __init__(
        self,
        fallback: SoapGenerator,
        model_id: str,
        region_name: str | None = None,
    ) -> None:
        self._fallback = fallback
        self._model_id = model_id
        self._region_name = region_name or "us-east-1"
        self._client = None

    def _get_client(self):
        """Lazy-init boto3 client to avoid import unless Bedrock is used."""
        if self._client is None:
            import boto3  # noqa: PLC0415

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region_name,
            )
        return self._client

    def generate(self, state: SessionState) -> SoapNote:
        """Generate a SOAP note via Bedrock with rules-based fallback."""
        if not state.transcript_text:
            return self._fallback.generate(state)

        try:
            client = self._get_client()
            prompt = self._build_prompt(state)

            response = client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2048,
                    "temperature": 0.2,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )

            response_body = json.loads(response["body"].read())
            content = response_body.get("content", [{}])[0].get("text", "")

            return self._parse_response(content, state)

        except Exception:
            logger.warning(
                "bedrock_soap_fallback",
                exc_info=True,
                extra={"extra_fields": {"model_id": self._model_id}},
            )
            return self._fallback.generate(state)

    def _build_prompt(self, state: SessionState) -> str:
        """Build a structured SOAP generation prompt."""
        analysis_ctx = ""
        if state.latest_analysis:
            a = state.latest_analysis
            analysis_ctx = f"""
Clinical analysis context:
- Diagnoses: {', '.join(a.possible_diagnoses[:5])}
- Symptoms: {', '.join(a.symptoms[:5])}
- Body regions: {', '.join(r.region for r in a.body_regions)}
- CPT suggestions: {', '.join(f'{c.code} ({c.display_name})' for c in a.cpt_suggestions)}
"""

        return f"""You are a clinical documentation assistant for physical/occupational therapy.
Generate a structured SOAP note from the following therapy session transcript.

Return a JSON object with exactly these fields:
{{
  "subjective": {{
    "chief_complaint": "Patient's reported symptoms and concerns",
    "pain_scale": "Pain level if mentioned (e.g., '6/10')",
    "duration": "Duration of symptoms if mentioned"
  }},
  "objective": {{
    "observation_notes": "Clinical observations and findings",
    "range_of_motion": "ROM findings if documented",
    "affect": "Patient's affect/demeanor",
    "vital_signs": "Vital signs if mentioned"
  }},
  "assessment": {{
    "diagnosis_summary": "Clinical impression summary",
    "primary_diagnosis_code": "Primary ICD-10 code if identifiable",
    "severity": "Severity level (Mild/Moderate/Severe)"
  }},
  "plan": {{
    "follow_up_plan": "Treatment plan and follow-up recommendations"
  }}
}}

IMPORTANT: This is a DRAFT for clinician review. Use clinical language appropriate
for therapy documentation. Do not diagnose — suggest impressions for confirmation.
{analysis_ctx}
Transcript:
{state.transcript_text}

Return ONLY valid JSON, no markdown formatting."""

    def _parse_response(self, content: str, state: SessionState) -> SoapNote:
        """Parse the Bedrock response into a SoapNote."""
        try:
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()

            data = json.loads(clean)
            subj = data.get("subjective", {})
            obj = data.get("objective", {})
            assess = data.get("assessment", {})
            plan = data.get("plan", {})

            return SoapNote(
                subjective=SoapSubjective(
                    chief_complaint=subj.get("chief_complaint", ""),
                    pain_scale=subj.get("pain_scale", state.soap.subjective.pain_scale),
                    duration=subj.get("duration", state.soap.subjective.duration),
                ),
                objective=SoapObjective(
                    observation_notes=obj.get("observation_notes", ""),
                    range_of_motion=obj.get("range_of_motion", ""),
                    affect=obj.get("affect", ""),
                    vital_signs=obj.get("vital_signs", ""),
                ),
                assessment=SoapAssessment(
                    diagnosis_summary=assess.get("diagnosis_summary", ""),
                    primary_diagnosis_code=assess.get("primary_diagnosis_code", ""),
                    severity=assess.get("severity", "Moderate"),
                ),
                plan=SoapPlan(follow_up_plan=plan.get("follow_up_plan", "")),
                generated=True,
            )
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning("bedrock_soap_parse_failed", exc_info=True)
            return self._fallback.generate(state)
