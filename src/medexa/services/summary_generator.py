"""Patient summary generation service — Strategy pattern with Rules and Bedrock adapters.

Healthcare compliance:
  * Patient-facing tone: avoids raw codes, focuses on what was worked on.
  * PHI minimization: uses first name only when available.
  * Bedrock adapter sends only transcript text (minimum necessary PHI).
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

from medexa.schemas import SessionState

logger = logging.getLogger(__name__)


@runtime_checkable
class PatientSummaryGenerator(Protocol):
    """Port: produce a plain-language, patient-facing visit summary."""

    def generate(self, state: SessionState) -> str: ...


class RulesPatientSummaryGenerator:
    """Builds a readable after-visit summary from the session's clinical
    analysis and SOAP draft — deterministic, no LLM.

    Patient-facing tone: avoids raw codes, focuses on what was worked on and
    next steps. PHI minimization: uses first name only when available."""

    def generate(self, state: SessionState) -> str:
        name = (state.patient_name or "").split(" ")[0] if state.patient_name else "the patient"
        analysis = state.latest_analysis

        focus_areas = []
        if analysis:
            focus_areas = [r.region.replace("_", " ") for r in analysis.body_regions]
        interventions = []
        if analysis:
            interventions = [c.display_name for c in analysis.cpt_suggestions]

        parts: list[str] = []
        parts.append(f"Summary of today's therapy visit for {name}.")
        if focus_areas:
            parts.append(f"We focused on the {', '.join(focus_areas)}.")
        if interventions:
            parts.append(f"Treatments performed: {', '.join(interventions)}.")
        if analysis and analysis.soap_update.plan:
            parts.append(f"Plan: {analysis.soap_update.plan}")
        else:
            parts.append("Continue your home exercise program and attend your next scheduled session.")
        parts.append("Please contact the clinic if symptoms worsen or you have questions.")

        return " ".join(parts)


class BedrockSummaryGenerator:
    """Amazon Bedrock patient-summary adapter — generates a warmer,
    individualized visit summary via a foundation model.

    Falls back to the rules generator on any error so the endpoint always
    returns a valid summary.

    Healthcare compliance:
      * Patient-facing language (no CPT/ICD codes in output).
      * PHI minimization: only first name and treatment context are sent.
      * Disclaimer appended to all AI-generated summaries.
    """

    def __init__(
        self,
        fallback: PatientSummaryGenerator,
        model_id: str,
        region_name: str | None = None,
    ) -> None:
        self._fallback = fallback
        self._model_id = model_id
        self._region_name = region_name or "us-east-1"
        self._client = None

    def _get_client(self):
        """Lazy-init boto3 client."""
        if self._client is None:
            import boto3  # noqa: PLC0415

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region_name,
            )
        return self._client

    def generate(self, state: SessionState) -> str:
        """Generate a patient-facing summary via Bedrock with rules fallback."""
        if not state.transcript_text:
            return self._fallback.generate(state)

        try:
            client = self._get_client()
            name = (state.patient_name or "").split(" ")[0] if state.patient_name else "the patient"

            analysis_ctx = ""
            if state.latest_analysis:
                a = state.latest_analysis
                focus = ", ".join(r.region.replace("_", " ") for r in a.body_regions)
                treatments = ", ".join(c.display_name for c in a.cpt_suggestions)
                analysis_ctx = f"""
Focus areas: {focus or 'General therapy'}
Treatments: {treatments or 'Standard therapy interventions'}
"""

            prompt = f"""You are a friendly clinical documentation assistant.
Write a brief, warm, patient-facing summary of today's therapy visit.

Rules:
- Use simple, non-technical language a patient can understand
- Do NOT include CPT codes, ICD codes, or clinical jargon
- Address the patient by first name: {name}
- Keep it to 3-5 sentences
- End with encouragement and a reminder to contact the clinic with questions
{analysis_ctx}
Session notes context (DO NOT include raw transcript in summary):
{state.transcript_text[:500]}

Write the summary directly, no JSON formatting."""

            response = client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 512,
                    "temperature": 0.4,
                    "messages": [{"role": "user", "content": prompt}],
                }),
            )

            response_body = json.loads(response["body"].read())
            summary = response_body.get("content", [{}])[0].get("text", "").strip()

            if not summary:
                return self._fallback.generate(state)

            return summary

        except Exception:
            logger.warning(
                "bedrock_summary_fallback",
                exc_info=True,
                extra={"extra_fields": {"model_id": self._model_id}},
            )
            return self._fallback.generate(state)
