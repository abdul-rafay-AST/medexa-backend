from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BedrockConverseClient:
    """Thin wrapper around Bedrock Runtime ``converse`` for Path B/C."""

    def __init__(self, model_id: str, region_name: str) -> None:
        self._model_id = model_id
        self._region_name = region_name
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3  # noqa: PLC0415

            self._client = boto3.client("bedrock-runtime", region_name=self._region_name)
        return self._client

    def converse(
        self,
        *,
        system: str,
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        client = self._get_client()
        response = client.converse(
            modelId=self._model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        )
        content = response.get("output", {}).get("message", {}).get("content", [])
        if not content:
            return ""
        return str(content[0].get("text", ""))
