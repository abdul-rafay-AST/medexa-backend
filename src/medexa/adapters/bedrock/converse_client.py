from __future__ import annotations

import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from medexa.adapters.bedrock.model_resolver import bedrock_model_candidates

logger = logging.getLogger(__name__)


class BedrockConverseError(RuntimeError):
    """Raised when every Bedrock model candidate fails."""


class BedrockConverseClient:
    """Thin wrapper around Bedrock Runtime ``converse`` for Path B/C."""

    def __init__(self, model_id: str, region_name: str) -> None:
        self._model_id = model_id.strip()
        self._region_name = region_name.strip()
        self._client: Any = None
        self._resolved_model_id: str | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3  # noqa: PLC0415

            self._client = boto3.client("bedrock-runtime", region_name=self._region_name)
        return self._client

    @property
    def resolved_model_id(self) -> str:
        return self._resolved_model_id or self._model_id

    def converse(
        self,
        *,
        system: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        client = self._get_client()
        errors: list[str] = []
        for candidate in bedrock_model_candidates(self._model_id):
            try:
                response = client.converse(
                    modelId=candidate,
                    system=[{"text": system}],
                    messages=[{"role": "user", "content": [{"text": user_message}]}],
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                self._resolved_model_id = candidate
                content = response.get("output", {}).get("message", {}).get("content", [])
                if not content:
                    return ""
                return str(content[0].get("text", ""))
            except (ClientError, BotoCoreError) as exc:
                errors.append(f"{candidate}: {exc}")
                logger.warning(
                    "bedrock_converse_candidate_failed",
                    extra={"extra_fields": {"model_id": candidate, "error": str(exc)}},
                )
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
                logger.warning(
                    "bedrock_converse_candidate_failed",
                    extra={"extra_fields": {"model_id": candidate, "error": str(exc)}},
                )

        joined = "; ".join(errors) or "no model candidates"
        raise BedrockConverseError(f"Bedrock converse failed for all model IDs: {joined}")
