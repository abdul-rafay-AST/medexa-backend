from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from medexa.adapters.fhir._common import (
    base_organization_resource,
    base_patient_resource,
    bundle_entry,
    claim_items_from_summary,
    fhir_instant,
    load_fhir_profile,
    reference,
)
from medexa.regions.bundle import RegionBundle
from medexa.schemas import BillingSummary, SessionState


@dataclass(frozen=True)
class UaeFhirR4Builder:
    """FHIR collection bundle used as an internal bridge to Shafafiya / eClaimLink."""

    bundle: RegionBundle

    def profile_id(self) -> str:
        profile = load_fhir_profile(self.bundle, "fhir/fhir_r4_profile_ae.json")
        emirate = "generic"
        return str(profile.get("profile_id", f"uae-emirate-claim-{emirate}"))

    def build_claim_bundle(self, state: SessionState, summary: BillingSummary) -> dict[str, Any]:
        profile = load_fhir_profile(self.bundle, "fhir/fhir_r4_profile_ae.json")
        bundle_id = str(uuid.uuid4())
        claim_id = str(uuid.uuid4())
        patient_id = str(uuid.uuid4())
        provider_id = str(uuid.uuid4())
        payer_id = str(uuid.uuid4())
        emirate = state.emirate or "UNKNOWN"
        bridge = profile.get("emirate_profiles", {}).get(emirate, "custom")

        claim_resource: dict[str, Any] = {
            "resourceType": "Claim",
            "id": claim_id,
            "meta": {
                "profile": [profile.get("claim_profile", "")],
                "tag": [{"system": "http://medexa.internal/emirate", "code": emirate}],
            },
            "status": "active",
            "use": "claim",
            "patient": reference("Patient", patient_id),
            "created": fhir_instant(summary.generated_at),
            "provider": reference("Organization", provider_id),
            "insurer": reference("Organization", payer_id),
            "extension": [
                {
                    "url": "http://medexa.internal/exchange-bridge",
                    "valueString": bridge,
                }
            ],
            "insurance": [
                {
                    "sequence": 1,
                    "focal": True,
                    "coverage": {"display": state.payer_id or "unknown-payer"},
                    "preAuthRef": state.pre_auth_reference,
                }
            ],
            "item": claim_items_from_summary(summary),
        }

        entries = [
            bundle_entry(base_patient_resource(state, patient_id), full_url=f"urn:uuid:{patient_id}"),
            bundle_entry(
                base_organization_resource(state, provider_id, org_type="provider"),
                full_url=f"urn:uuid:{provider_id}",
            ),
            bundle_entry(
                base_organization_resource(state, payer_id, org_type="insurer"),
                full_url=f"urn:uuid:{payer_id}",
            ),
            bundle_entry(claim_resource, full_url=f"urn:uuid:{claim_id}"),
        ]

        return {
            "resourceType": "Bundle",
            "id": bundle_id,
            "type": profile.get("bundle_type", "collection"),
            "timestamp": fhir_instant(summary.generated_at),
            "entry": entries,
        }
