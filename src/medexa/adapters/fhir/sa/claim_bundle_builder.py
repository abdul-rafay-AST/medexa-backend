from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from medexa.adapters.fhir._common import (
    deep_copy_template,
    find_extension,
    find_organization,
    find_resource,
    fhir_instant,
    load_bundle_template,
    load_fhir_profile,
    new_resource_ids,
    rewrite_references,
)
from medexa.adapters.fhir.sa.clinical_claim_fill import apply_clinical_claim_fill
from medexa.regions.bundle import RegionBundle
from medexa.regions.sa.detection.catalog import SaBillingCatalog, load_sa_catalog
from medexa.schemas import BillingSummary, SessionState


@dataclass
class NphiesClaimBundleBuilder:
    """Builds a NPHIES-compliant professional claim-request Bundle.

    Starts from the validated structural template
    (``config/regions/sa/fhir/templates/professional-claim-request-bundle.template.json``)
    so every mandatory NPHIES element (extension-episode, full supportingInfo,
    item extension-maternity/extension-patientInvoice, encounter-claim-AMB
    profile, ``services`` CodeSystem) is always present.

    Clinical diagnosis + treatment lines are filled from the session the same
    way as BillingEngine ``nphies_claim_builder`` (ICD insights + SBS lines).
    """

    bundle: RegionBundle
    _catalog: SaBillingCatalog | None = field(default=None, init=False, repr=False)

    def profile_id(self) -> str:
        profile = self._profile()
        return str(profile.get("profile_id", "nphies-professional-claim"))

    def _profile(self) -> dict[str, Any]:
        return load_fhir_profile(self.bundle, "fhir/fhir_r4_profile_sa.json")

    def _sa_catalog(self) -> SaBillingCatalog | None:
        if self._catalog is None:
            try:
                self._catalog = load_sa_catalog(self.bundle)
            except Exception:
                self._catalog = None
        return self._catalog

    def build_claim_bundle(self, state: SessionState, summary: BillingSummary) -> dict[str, Any]:
        profile = self._profile()
        template_path = profile.get(
            "claim_request_template",
            "fhir/templates/professional-claim-request-bundle.template.json",
        )
        template = deep_copy_template(load_bundle_template(self.bundle, template_path))

        roles = new_resource_ids(template)
        rewrite_references(template, roles)

        now = summary.generated_at
        template["id"] = str(uuid.uuid4())
        template["timestamp"] = fhir_instant(now)

        message_header = find_resource(template, "MessageHeader")
        message_header["destination"][0]["receiver"]["identifier"]["value"] = state.payer_id or ""
        message_header["sender"]["identifier"]["value"] = state.therapist_id or ""
        message_header["source"]["endpoint"] = "https://medexa.internal/nphies"

        claim = find_resource(template, "Claim")
        claim["identifier"][0]["value"] = state.session_id
        claim["created"] = fhir_instant(now)

        episode_ext = find_extension(claim, "extension-episode")
        if episode_ext is not None:
            episode_ext["valueIdentifier"]["system"] = "https://medexa.internal/identifiers/episode"
            episode_ext["valueIdentifier"]["value"] = state.session_id

        if state.pre_auth_reference:
            claim["insurance"][0]["preAuthRef"] = [state.pre_auth_reference]

        care_team = claim.get("careTeam", [{}])[0]
        care_team.get("qualification", {}).get("coding", [{}])[0]["code"] = "16.00"
        care_team.get("qualification", {}).get("coding", [{}])[0]["display"] = (
            "Physical Medicine & Rehabilitation Specialty"
        )

        apply_clinical_claim_fill(
            claim,
            state,
            summary,
            self._sa_catalog(),
            include_patient_invoice=True,
        )

        patient = find_resource(template, "Patient")
        patient["identifier"][0]["value"] = state.member_id or state.mrn or state.patient_id or ""
        if state.patient_name:
            patient["name"][0]["text"] = state.patient_name
            parts = state.patient_name.split()
            patient["name"][0]["family"] = parts[-1] if parts else ""
            patient["name"][0]["given"] = parts[:-1] or [state.patient_name]

        coverage = find_resource(template, "Coverage")
        coverage["identifier"][0]["value"] = state.member_id or ""
        coverage["identifier"][0]["system"] = "https://medexa.internal/identifiers/member-id"

        provider_org = find_organization(template, "provider-organization|1.0.0")
        insurer_org = find_organization(template, "insurer-organization|1.0.0")
        if provider_org is not None:
            provider_org["identifier"][0]["value"] = state.therapist_id or ""
        if insurer_org is not None:
            insurer_org["identifier"][0]["value"] = state.payer_id or ""

        practitioner = find_resource(template, "Practitioner")
        practitioner["identifier"][0]["value"] = state.therapist_id or ""

        encounter = find_resource(template, "Encounter")
        encounter["period"]["start"] = fhir_instant(state.created_at)
        if summary.generated_at:
            encounter["period"]["end"] = fhir_instant(summary.generated_at)

        return template
