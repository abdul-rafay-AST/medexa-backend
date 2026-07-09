from __future__ import annotations

from typing import Protocol, runtime_checkable

from medexa.schemas import SessionState


@runtime_checkable
class DocumentationGeneratorPort(Protocol):
    """Path C — Bedrock Converse deep documentation."""

    def generate_soap(self, state: SessionState) -> object: ...
    def generate_summary(self, state: SessionState) -> str: ...
