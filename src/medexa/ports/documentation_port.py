from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from medexa.schemas import SoapNote


@dataclass(frozen=True)
class DocumentationResult:
    soap: SoapNote
    patient_summary: str
    source: str = "rules"


@runtime_checkable
class DocumentationPort(Protocol):
    """Path C — one-shot post-session documentation generation."""

    def generate(self, context: dict[str, Any]) -> DocumentationResult: ...
