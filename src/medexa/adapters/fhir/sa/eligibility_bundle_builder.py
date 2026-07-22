from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from medexa.adapters.fhir._common import (
    deep_copy_template,
    fill_shared_party_resources,
    find_resource,
    fhir_date,
    fhir_instant,
    load_bundle_template,
    load_fhir_profile,
    new_resource_ids,
    rewrite_references,
    stamp_bundle_envelope,
)
from medexa.regions.bundle import RegionBundle
from medexa.schemas import SessionState


@dataclass(frozen=True)
class NphiesEligibilityBundleBuilder:
    """Builds a NPHIES-compliant CoverageEligibilityRequest message Bundle.

    Template:
    ``config/regions/sa/fhir/templates/eligibility-request.template.json``

    Design:
    - Template holds static NPHIES structure (profiles, purpose, status).
    - Builder fills only Medexa-known session fields.
    - Fields that require clinic config / intake / payer directory remain empty
      so reviewers can see what is still missing before live NPHIES submit.
    - No ``item[]`` unless a benefit-category code is supplied (empty category
      codes are worse than omitting the optional item).

    Flow position: Eligibility → Prior-auth → Session/Claim.
    """

    bundle: RegionBundle

    def profile_id(self) -> str:
        return "nphies-eligibility-request"

    def _profile(self) -> dict[str, Any]:
        return load_fhir_profile(self.bundle, "fhir/fhir_r4_profile_sa.json")

    def build_eligibility_bundle(
        self,
        state: SessionState,
        *,
        as_of: datetime | None = None,
        purpose: tuple[str, ...] = ("validation", "benefits"),
        benefit_category_code: str | None = None,
    ) -> dict[str, Any]:
        profile = self._profile()
        template_path = profile.get(
            "eligibility_request_template",
            "fhir/templates/eligibility-request.template.json",
        )
        template = deep_copy_template(load_bundle_template(self.bundle, template_path))

        roles = new_resource_ids(template)
        rewrite_references(template, roles)

        when = as_of or state.created_at
        stamp_bundle_envelope(template, when)
        fill_shared_party_resources(template, state)

        request = find_resource(template, "CoverageEligibilityRequest")
        request["identifier"][0]["value"] = state.session_id
        request["created"] = fhir_instant(when)
        request["purpose"] = list(dict.fromkeys(purpose))  # unique, ordered
        request["servicedPeriod"] = {
            "start": fhir_date(when),
            "end": fhir_date(when),
        }

        if benefit_category_code:
            request["item"] = [
                {
                    "category": {
                        "coding": [
                            {
                                "system": "http://nphies.sa/terminology/CodeSystem/benefit-category",
                                "code": benefit_category_code,
                            }
                        ]
                    }
                }
            ]

        return template
