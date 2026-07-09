from __future__ import annotations

from medexa.application.session_context_builder import SessionFinalizeContext
from medexa.ports.documentation_port import DocumentationPort, DocumentationResult
from medexa.schemas import SessionState


class DocumentationService:
    """Facade — selects Path C generator and enriches context with session state."""

    def __init__(self, generator: DocumentationPort) -> None:
        self._generator = generator

    def generate(self, state: SessionState, context: SessionFinalizeContext) -> DocumentationResult:
        payload = context.to_prompt_dict()
        payload["state"] = state
        return self._generator.generate(payload)
