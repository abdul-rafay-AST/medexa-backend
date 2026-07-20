from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from medexa.aws.paths import fhir_export_key
from medexa.domain.fhir_export import FhirExportArtifact
from medexa.ports.fhir_export_port import FhirExportPort, PriorAuthFhirExportPort
from medexa.ports.object_storage import ObjectStoragePort
from medexa.schemas import BillingSummary, SessionState


@dataclass(frozen=True)
class FhirExportService:
    """Persists region-specific FHIR claim / prior-auth bundles to object storage."""

    def export_session(
        self,
        state: SessionState,
        summary: BillingSummary,
        exporter: FhirExportPort,
        storage: ObjectStoragePort | None,
        *,
        filename: str = "claim-bundle.json",
    ) -> FhirExportArtifact:
        bundle = exporter.build_claim_bundle(state, summary)
        return self._persist(state, exporter.profile_id(), bundle, storage, filename)

    def export_priorauth(
        self,
        state: SessionState,
        summary: BillingSummary,
        exporter: PriorAuthFhirExportPort,
        storage: ObjectStoragePort | None,
        *,
        filename: str = "priorauth-bundle.json",
    ) -> FhirExportArtifact:
        bundle = exporter.build_priorauth_bundle(state, summary)
        return self._persist(state, exporter.profile_id(), bundle, storage, filename)

    def _persist(
        self,
        state: SessionState,
        profile_id: str,
        bundle: dict,
        storage: ObjectStoragePort | None,
        filename: str,
    ) -> FhirExportArtifact:
        payload = json.dumps(bundle, indent=2, ensure_ascii=False).encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()
        bundle_id = str(bundle.get("id", uuid.uuid4()))
        key = fhir_export_key(state.billing_region, state.session_id, filename)

        storage_uri: str | None = None
        if storage is not None:
            storage.put_bytes(key, payload, content_type="application/fhir+json")
            storage_uri = storage.uri(key)

        return FhirExportArtifact(
            session_id=state.session_id,
            billing_region=state.billing_region,
            profile_id=profile_id,
            bundle_id=bundle_id,
            storage_uri=storage_uri,
            storage_key=key if storage is not None else None,
            byte_size=len(payload),
            checksum_sha256=checksum,
        )
