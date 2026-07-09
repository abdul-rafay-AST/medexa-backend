from __future__ import annotations

from typing import Any


class NoOpClinicalAssistant:
    """Path B fallback when Bedrock is disabled — no LLM calls."""

    async def suggest(
        self,
        session_id: str,
        buffered_transcript: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return []
