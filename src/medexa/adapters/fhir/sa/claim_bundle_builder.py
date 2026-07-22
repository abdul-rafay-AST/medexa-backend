from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from medexa.adapters.fhir._common import (
    SERVICES_CODE_SYSTEM,
    deep_copy_template,
    fill_shared_party_resources,
    find_extension,
    find_resource,
    fhir_instant,
    load_bundle_template,
    load_fhir_profile,
    new_resource_ids,
    rewrite_references,
    set_rehab_care_team_qualification,
    stamp_bundle_envelope,
)
from medexa.adapters.fhir.sa.clinical_claim_fill import apply_clinical_claim_fill
from medexa.regions.bundle import RegionBundle
from medexa.regions.sa.detection.catalog import SaBillingCatalog, load_sa_catalog
from medexa.schemas import BillingSummary, SessionState


@dataclass
class NphiesClaimBundleBuilder:
    """Builds a NPHIES-compliant professional claim-request Bundle.

    Starts from the validated structural template
    (``config/regions/sa/fhir/templates/claim-request.template.json``)
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
            "fhir/templates/claim-request.template.json",
        )
        template = deep_copy_template(load_bundle_template(self.bundle, template_path))

        roles = new_resource_ids(template)
        rewrite_references(template, roles)

        now = summary.generated_at
        stamp_bundle_envelope(template, now)
        fill_shared_party_resources(template, state)

        claim = find_resource(template, "Claim")
        claim["identifier"][0]["value"] = state.session_id
        claim["created"] = fhir_instant(now)

        episode_ext = find_extension(claim, "extension-episode")
        if episode_ext is not None:
            episode_ext["valueIdentifier"]["system"] = (
                "https://medexa.internal/identifiers/episode"
            )
            episode_ext["valueIdentifier"]["value"] = state.session_id

        if state.pre_auth_reference:
            claim["insurance"][0]["preAuthRef"] = [state.pre_auth_reference]

        set_rehab_care_team_qualification(claim)

        apply_clinical_claim_fill(
            claim,
            state,
            summary,
            self._sa_catalog(),
            include_patient_invoice=True,
        )

        encounter = find_resource(template, "Encounter")
        encounter["period"]["start"] = fhir_instant(state.created_at)
        encounter["period"]["end"] = fhir_instant(now)

        return template

