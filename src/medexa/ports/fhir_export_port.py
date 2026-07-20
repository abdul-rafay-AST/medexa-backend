from __future__ import annotations

from typing import Any, Protocol

from medexa.schemas import BillingSummary, SessionState


class FhirExportPort(Protocol):
    """Builds a region-specific FHIR R4 claim bundle from session state."""

    def profile_id(self) -> str: ...

    def build_claim_bundle(self, state: SessionState, summary: BillingSummary) -> dict[str, Any]: ...


class PriorAuthFhirExportPort(Protocol):
    """Builds a region-specific FHIR R4 prior-authorization request Bundle."""

    def profile_id(self) -> str: ...

    def build_priorauth_bundle(
        self, state: SessionState, summary: BillingSummary
    ) -> dict[str, Any]: ...
