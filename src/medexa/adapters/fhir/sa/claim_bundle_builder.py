from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from medexa.adapters.fhir._common import (
    base_organization_resource,
    base_patient_resource,
    bundle_entry,
    claim_items_from_summary,
    coding,
    fhir_instant,
    load_fhir_profile,
    reference,
)
from medexa.regions.bundle import RegionBundle
from medexa.schemas import BillingSummary, SessionState


@dataclass(frozen=True)
class NphiesClaimBundleBuilder:
    bundle: RegionBundle

    def profile_id(self) -> str:
        profile = load_fhir_profile(self.bundle, "fhir/fhir_r4_profile_sa.json")
        return str(profile.get("profile_id", "nphies-professional-claim"))

    def build_claim_bundle(self, state: SessionState, summary: BillingSummary) -> dict[str, Any]:
        profile = load_fhir_profile(self.bundle, "fhir/fhir_r4_profile_sa.json")
        bundle_id = str(uuid.uuid4())
        message_id = str(uuid.uuid4())
        claim_id = str(uuid.uuid4())
        patient_id = str(uuid.uuid4())
        provider_id = str(uuid.uuid4())
        insurer_id = str(uuid.uuid4())
        now = summary.generated_at

        claim_resource: dict[str, Any] = {
            "resourceType": "Claim",
            "id": claim_id,
            "meta": {
                "profile": [profile.get("claim_profile", "")],
            },
            "status": "active",
            "type": {
                "coding": [
                    coding(
                        str(profile.get("claim_type_system", "")),
                        str(profile.get("claim_type_code", "professional")),
                        "Professional",
                    )
                ]
            },
            "use": "claim",
            "patient": reference("Patient", patient_id),
            "created": fhir_instant(now),
            "provider": reference("Organization", provider_id),
            "insurer": reference("Organization", insurer_id),
            "priority": {"coding": [coding("http://terminology.hl7.org/CodeSystem/processpriority", "normal")]},
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

        message_header = {
            "resourceType": "MessageHeader",
            "id": message_id,
            "meta": {"profile": [profile.get("message_profile", "")]},
            "eventCoding": coding(
                "http://nphies.sa/terminology/CodeSystem/ksa-message-events",
                "claim-request",
                "Claim Request",
            ),
            "destination": [{"endpoint": "http://nphies.sa"}],
            "sender": reference("Organization", provider_id),
            "source": {"endpoint": "https://medexa.internal/nphies"},
            "focus": [reference("Claim", claim_id)],
        }

        entries = [
            bundle_entry(message_header, full_url=f"urn:uuid:{message_id}"),
            bundle_entry(base_patient_resource(state, patient_id), full_url=f"urn:uuid:{patient_id}"),
            bundle_entry(
                base_organization_resource(state, provider_id, org_type="provider"),
                full_url=f"urn:uuid:{provider_id}",
            ),
            bundle_entry(
                base_organization_resource(state, insurer_id, org_type="insurer"),
                full_url=f"urn:uuid:{insurer_id}",
            ),
            bundle_entry(claim_resource, full_url=f"urn:uuid:{claim_id}"),
        ]

        return {
            "resourceType": "Bundle",
            "id": bundle_id,
            "type": profile.get("bundle_type", "message"),
            "timestamp": fhir_instant(now),
            "entry": entries,
        }
