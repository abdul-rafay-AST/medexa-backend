from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ClinicalAssistantPort(Protocol):
    """Path B only — Bedrock fast model. Not used on chunk ingest (Phase 3)."""

    async def suggest(self, session_id: str, buffered_transcript: str, context: dict[str, Any]) -> list[dict[str, Any]]: ...
