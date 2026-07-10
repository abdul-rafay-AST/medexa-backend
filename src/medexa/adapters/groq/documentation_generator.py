from __future__ import annotations

import json
import logging
from typing import Any

from medexa.adapters.groq.client import GroqClient, GroqClientError
from medexa.adapters.llm.path_prompts import PATH_C_SYSTEM_PROMPT
from medexa.ports.documentation_port import DocumentationPort, DocumentationResult
from medexa.ports.guardrails import GuardrailsPort
from medexa.schemas import (
    SoapAssessment,
    SoapNote,
    SoapObjective,
    SoapPlan,
    SoapSubjective,
)

logger = logging.getLogger(__name__)


class GroqDocumentationGenerator:
    """Path C — single Groq chat call for SOAP + patient summary."""

    def __init__(
        self,
        *,
        fallback: DocumentationPort,
        api_key: str,
        model_id: str,
        guardrails: GuardrailsPort,
        base_url: str | None = None,
    ) -> None:
        self._fallback = fallback
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = GroqClient(**kwargs)
        self._guardrails = guardrails
        self._model_id = model_id

    def generate(self, context: dict[str, Any]) -> DocumentationResult:
        transcript = str(context.get("full_transcript", "")).strip()
        if not transcript:
            return self._fallback.generate(context)

        scrubbed = self._guardrails.scrub_phi(transcript)
        user_prompt = self._build_prompt(context, scrubbed)

        try:
            raw = self._client.chat(
                model=self._model_id,
                system=PATH_C_SYSTEM_PROMPT,
                user_message=user_prompt,
                max_tokens=4096,
                temperature=0.2,
            )
            return self._parse_response(raw)
        except (GroqClientError, Exception):
            logger.warning(
                "groq_path_c_fallback",
                exc_info=True,
                extra={"extra_fields": {"model_id": self._model_id}},
            )
            return self._fallback.generate(context)

    def _build_prompt(self, context: dict[str, Any], transcript: str) -> str:
        return f"""Session ID: {context.get("session_id")}
Billing region: {context.get("billing_region")}
Patient first name: {context.get("patient_first_name", "the patient")}

Timeline events:
{json.dumps(context.get("timeline", [])[:20], indent=2)}

Path A alerts:
{json.dumps(context.get("alerts", [])[:10], indent=2)}

Applied billing suggestions (informational):
{json.dumps(context.get("applied_suggestions", [])[:10], indent=2)}

Path B assistant hints:
{json.dumps(context.get("assistant_hints", [])[:6], indent=2)}

Timer summary (informational, do not override billing engine):
{json.dumps(context.get("timer_summary", [])[:10], indent=2)}

Structured clinical evidence (authoritative — do not omit specifics):
{json.dumps(context.get("clinical_evidence", {}), indent=2)}

Full transcript:
{transcript}
"""

    def _parse_response(self, raw: str) -> DocumentationResult:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        data = json.loads(clean)
        soap_data = data.get("soap", {})
        subj = soap_data.get("subjective", {})
        obj = soap_data.get("objective", {})
        assess = soap_data.get("assessment", {})
        plan = soap_data.get("plan", {})
        summary = self._guardrails.validate_assistant_output(
            str(data.get("patient_summary", "")).strip()
        )

        soap = SoapNote(
            subjective=SoapSubjective(
                chief_complaint=subj.get("chief_complaint", ""),
                pain_scale=subj.get("pain_scale", ""),
                duration=subj.get("duration", ""),
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
        return DocumentationResult(soap=soap, patient_summary=summary, source="groq")
