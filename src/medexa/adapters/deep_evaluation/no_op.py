from __future__ import annotations

from typing import Any


class NoOpDeepEvaluation:
    """HealthScribe / deep audio evaluation placeholder."""

    def evaluate(self, session_id: str, *, audio_uri: str | None = None) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "status": "not_configured",
            "audio_uri": audio_uri,
            "message": "Deep evaluation adapter not wired (future HealthScribe integration).",
        }
