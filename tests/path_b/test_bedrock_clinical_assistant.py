from __future__ import annotations

import json

import pytest

from medexa.adapters.bedrock.clinical_assistant import BedrockClinicalAssistant
from medexa.adapters.guardrails.local_guardrails import LocalGuardrails


class _FakeConverseClient:
  def __init__(self, response: str) -> None:
      self._response = response
      self.calls = 0

  def converse(self, **kwargs: object) -> str:
      self.calls += 1
      return self._response


@pytest.mark.asyncio
async def test_bedrock_assistant_parses_json_suggestions() -> None:
    payload = {
        "suggestions": [
            {
                "kind": "clinical_question",
                "title": "ROM baseline",
                "body": "Consider documenting baseline ROM.",
                "confidence": "medium",
            }
        ]
    }
    client = _FakeConverseClient(json.dumps(payload))
    assistant = BedrockClinicalAssistant(
        model_id="test-model",
        region_name="us-east-1",
        guardrails=LocalGuardrails(),
    )
    assistant._client = client  # type: ignore[assignment]

    results = await assistant.suggest("s1", "patient knee pain", {"trigger_reason": "interval"})
    assert client.calls == 1
    assert len(results) == 1
    assert results[0]["title"] == "ROM baseline"
    assert "clinician review" in results[0]["body"]
