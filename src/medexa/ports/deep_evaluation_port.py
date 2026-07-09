from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DeepEvaluationPort(Protocol):
    """Future HealthScribe / deep audio evaluation hook (Path C extension)."""

    def evaluate(self, session_id: str, *, audio_uri: str | None = None) -> dict[str, Any]: ...
