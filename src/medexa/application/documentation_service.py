from __future__ import annotations

from medexa.application.session_context_builder import SessionFinalizeContext
from medexa.application.session_clinical_evidence import SessionClinicalEvidenceBuilder
from medexa.application.soap_enricher import SoapEnricher
from medexa.loaders.icd_lookup_loader import IcdLookupLoader
from medexa.ports.documentation_port import DocumentationPort, DocumentationResult
from medexa.schemas import SessionState


class DocumentationService:
    """Facade — selects Path C generator and enriches context with session state."""

    def __init__(
        self,
        generator: DocumentationPort,
        *,
        icd_loader: IcdLookupLoader | None = None,
    ) -> None:
        self._generator = generator
        self._clinical_evidence_builder = SessionClinicalEvidenceBuilder(icd_loader)
        self._soap_enricher = SoapEnricher()

    def generate(self, state: SessionState, context: SessionFinalizeContext) -> DocumentationResult:
        payload = context.to_prompt_dict()
        payload["state"] = state
        result = self._generator.generate(payload)
        transcript = str(payload.get("full_transcript") or state.transcript_text)
        evidence = self._clinical_evidence_builder.build(state, full_transcript=transcript)
        enriched_soap = self._soap_enricher.enrich(result.soap, evidence, state)
        return DocumentationResult(
            soap=enriched_soap,
            patient_summary=result.patient_summary,
            source=result.source,
        )
