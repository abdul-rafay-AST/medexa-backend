from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from medexa.utils.time import now_utc

Confidence = Literal["low", "medium", "high"]
AssistantSuggestionKind = Literal[
    "documentation_reminder",
    "missing_information",
    "clinical_question",
    "general",
]


class AssistantSuggestion(BaseModel):
    """Path B output — separate from billing ``Suggestion`` (CPT timer)."""

    suggestion_id: str
    session_id: str
    trigger_id: str
    kind: AssistantSuggestionKind = "general"
    title: str
    body: str
    confidence: Confidence = "medium"
    status: Literal["active", "dismissed"] = "active"
    disclaimer: str = "AI-generated suggestions require clinician review before use."
    created_at: datetime = Field(default_factory=now_utc)

    @classmethod
    def from_model_payload(
        cls,
        *,
        session_id: str,
        trigger_id: str,
        payload: dict[str, Any],
    ) -> AssistantSuggestion:
        return cls(
            suggestion_id=str(payload.get("suggestion_id", uuid.uuid4())),
            session_id=session_id,
            trigger_id=trigger_id,
            kind=payload.get("kind", "general"),  # type: ignore[arg-type]
            title=str(payload.get("title", "Documentation note")),
            body=str(payload.get("body", "")),
            confidence=payload.get("confidence", "medium"),  # type: ignore[arg-type]
        )
