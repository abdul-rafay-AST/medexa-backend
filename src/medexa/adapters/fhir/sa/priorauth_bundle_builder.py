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
class NphiesPriorAuthBundleBuilder:
    """Builds a NPHIES-compliant professional prior-authorization Bundle.

    Differences from claim:
    - ``use`` is ``preauthorization``
    - No ``extension-episode`` / patientInvoice
    - Links ``extension-eligibility-response``
    - Encounter uses ``encounter-auth-*`` (status ``in-progress``)
    - SBS codes bind to ``CodeSystem/services`` (not ``procedures``)
    - Clinical diagnosis + treatments filled like BillingEngine / claim builder
    """

    bundle: RegionBundle
    _catalog: SaBillingCatalog | None = field(default=None, init=False, repr=False)

    def profile_id(self) -> str:
        return "nphies-professional-priorauth"

    def _profile(self) -> dict[str, Any]:
        return load_fhir_profile(self.bundle, "fhir/fhir_r4_profile_sa.json")

    def _sa_catalog(self) -> SaBillingCatalog | None:
        if self._catalog is None:
            try:
                self._catalog = load_sa_catalog(self.bundle)
            except Exception:
                self._catalog = None
        return self._catalog

    def build_priorauth_bundle(self, state: SessionState, summary: BillingSummary) -> dict[str, Any]:
        profile = self._profile()
        template_path = profile.get(
            "priorauth_request_template",
            "fhir/templates/priorauth-request.template.json",
        )
        template = deep_copy_template(load_bundle_template(self.bundle, template_path))

        roles = new_resource_ids(template)
        rewrite_references(template, roles)

        now = summary.generated_at
        stamp_bundle_envelope(template, now)
        fill_shared_party_resources(template, state)

        claim = find_resource(template, "Claim")
        claim["identifier"][0]["system"] = "https://medexa.internal/identifiers/authorization"
        claim["identifier"][0]["value"] = state.session_id
        claim["created"] = fhir_instant(now)
        claim["subType"] = {
            "coding": [
                {
                    "system": "http://nphies.sa/terminology/CodeSystem/claim-subtype",
                    "code": "op",
                    "display": "Outpatient",
                }
            ]
        }

        eligibility_ext = find_extension(claim, "extension-eligibility-response")
        if eligibility_ext is not None:
            eligibility_ext["valueReference"]["identifier"]["system"] = (
                "https://medexa.internal/identifiers/eligibility-response"
            )
            eligibility_value = ""
            if state.pre_auth_snapshot is not None:
                raw = state.pre_auth_snapshot.raw or {}
                eligibility_value = str(
                    raw.get("eligibility_response_id")
                    or raw.get("reference")
                    or getattr(state.pre_auth_snapshot, "reference", "")
                    or ""
                )
            if not eligibility_value and state.pre_auth_reference:
                eligibility_value = state.pre_auth_reference
            eligibility_ext["valueReference"]["identifier"]["value"] = eligibility_value

        set_rehab_care_team_qualification(claim)

        apply_clinical_claim_fill(
            claim,
            state,
            summary,
            self._sa_catalog(),
            include_patient_invoice=False,
        )

        encounter = find_resource(template, "Encounter")
        encounter["period"]["start"] = fhir_instant(state.created_at)
        encounter["period"].pop("end", None)

        return template

