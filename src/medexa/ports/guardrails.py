from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class GuardrailsPort(Protocol):
    """PHI scrub + safety before any LLM call (Path B/C)."""

    def scrub_phi(self, text: str) -> str: ...
    def validate_assistant_output(self, text: str) -> str: ...
