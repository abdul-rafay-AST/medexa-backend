from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from medexa.adapters.groq.client import GroqClient, GroqClientError
from medexa.adapters.llm.path_prompts import PATH_B_SYSTEM_PROMPT
from medexa.ports.guardrails import GuardrailsPort

logger = logging.getLogger(__name__)


class GroqClinicalAssistant:
    """Path B — Groq chat model for live clinician assistance."""

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str,
        guardrails: GuardrailsPort,
        base_url: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = GroqClient(**kwargs)
        self._guardrails = guardrails
        self._model_id = model_id

    async def suggest(
        self,
        session_id: str,
        buffered_transcript: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not buffered_transcript.strip():
            return []

        scrubbed = self._guardrails.scrub_phi(buffered_transcript)
        user_prompt = self._build_user_prompt(session_id, scrubbed, context)

        try:
            raw = self._client.chat(
                model=self._model_id,
                system=PATH_B_SYSTEM_PROMPT,
                user_message=user_prompt,
                max_tokens=1536,
                temperature=0.2,
            )
            return self._parse_response(raw)
        except (GroqClientError, Exception):
            logger.warning(
                "groq_path_b_failed",
                exc_info=True,
                extra={"extra_fields": {"session_id": session_id, "model_id": self._model_id}},
            )
            return []

    def _build_user_prompt(self, session_id: str, transcript: str, context: dict[str, Any]) -> str:
        trigger_reason = context.get("trigger_reason", "interval")
        billing_region = context.get("billing_region", "US")
        active_cpt = context.get("active_cpt")
        alerts = context.get("alerts", [])
        alert_lines = [
            f"- {alert.get('alert_type', 'alert')}: {alert.get('message', '')}"
            for alert in alerts[:5]
        ]
        return f"""Session: {session_id}
Billing region: {billing_region}
Trigger reason: {trigger_reason}
Active therapy focus (informational only, do not bill): {active_cpt or "none"}

Path A alerts (for context, do not override billing):
{chr(10).join(alert_lines) if alert_lines else "- none"}

Recent transcript:
{transcript}

Return 1-4 concise suggestions as JSON."""

    def _parse_response(self, raw: str) -> list[dict[str, Any]]:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()

        try:
            payload = json.loads(clean)
        except json.JSONDecodeError:
            return self._fallback_single_suggestion(clean)

        suggestions = payload.get("suggestions", [])
        if not isinstance(suggestions, list):
            return []

        parsed: list[dict[str, Any]] = []
        for item in suggestions:
            if not isinstance(item, dict):
                continue
            body = str(item.get("body", "")).strip()
            if not body:
                continue
            try:
                body = self._guardrails.validate_assistant_output(body)
            except ValueError:
                continue
            parsed.append(
                {
                    "suggestion_id": str(uuid.uuid4()),
                    "kind": item.get("kind", "general"),
                    "title": str(item.get("title", "Documentation note")).strip()
                    or "Documentation note",
                    "body": body,
                    "confidence": item.get("confidence", "medium"),
                }
            )
        return parsed[:4]

    def _fallback_single_suggestion(self, text: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        try:
            body = self._guardrails.validate_assistant_output(text.strip())
        except ValueError:
            return []
        return [
            {
                "suggestion_id": str(uuid.uuid4()),
                "kind": "general",
                "title": "Documentation note",
                "body": body,
                "confidence": "low",
            }
        ]
