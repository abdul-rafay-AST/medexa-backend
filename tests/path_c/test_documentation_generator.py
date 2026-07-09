from __future__ import annotations

import json

import pytest

from medexa.adapters.bedrock.documentation_generator import BedrockDocumentationGenerator
from medexa.adapters.bedrock.documentation_generator import RulesDocumentationGenerator
from medexa.adapters.guardrails.local_guardrails import LocalGuardrails
from medexa.schemas import SessionState


class _FakeConverseClient:
    def __init__(self, response: str) -> None:
        self._response = response

    def converse(self, **kwargs: object) -> str:
        return self._response


def test_bedrock_documentation_generator_parses_soap_and_summary() -> None:
    payload = {
        "soap": {
            "subjective": {"chief_complaint": "Knee pain", "pain_scale": "5/10", "duration": "2 weeks"},
            "objective": {
                "observation_notes": "Antalgic gait",
                "range_of_motion": "Limited flexion",
                "affect": "Cooperative",
                "vital_signs": "",
            },
            "assessment": {
                "diagnosis_summary": "Knee pain, clinician to confirm",
                "primary_diagnosis_code": "",
                "severity": "Moderate",
            },
            "plan": {"follow_up_plan": "Continue HEP"},
        },
        "patient_summary": "Today we worked on knee mobility.",
    }
    generator = BedrockDocumentationGenerator(
        fallback=RulesDocumentationGenerator(),
        model_id="test-model",
        region_name="us-east-2",
        guardrails=LocalGuardrails(),
    )
    generator._client = _FakeConverseClient(json.dumps(payload))  # type: ignore[assignment]

    state = SessionState(session_id="s1", patient_name="Jamie Patient")
    result = generator.generate(
        {
            "state": state,
            "session_id": "s1",
            "billing_region": "US",
            "full_transcript": "Therapeutic exercise for knee.",
            "patient_first_name": "Jamie",
            "timeline": [],
            "alerts": [],
            "applied_suggestions": [],
            "assistant_hints": [],
            "timer_summary": [],
        }
    )
    assert result.source == "bedrock"
    assert result.soap.subjective.chief_complaint == "Knee pain"
    assert "clinician review" in result.patient_summary.lower()
