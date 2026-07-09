from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from medexa.domain.billing_region import BillingRegion


@dataclass(frozen=True)
class RegionProfile:
    billing_region: BillingRegion
    display_name: str
    icd_system: str
    billing_model: str
    uses_eight_minute_rule: bool
    uses_ncci: bool
    pre_authorization_required: bool
    pre_auth_provider: str | None
    fhir_export: bool
    fhir_version: str | None


def load_region_profile(path: Path) -> RegionProfile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return RegionProfile(
        billing_region=raw["region_id"],
        display_name=raw["display_name"],
        icd_system=raw["icd_system"],
        billing_model=raw["billing_model"],
        uses_eight_minute_rule=bool(raw["uses_eight_minute_rule"]),
        uses_ncci=bool(raw["uses_ncci"]),
        pre_authorization_required=bool(raw["pre_authorization_required"]),
        pre_auth_provider=raw.get("pre_auth_provider"),
        fhir_export=bool(raw["fhir_export"]),
        fhir_version=raw.get("fhir_version"),
    )
