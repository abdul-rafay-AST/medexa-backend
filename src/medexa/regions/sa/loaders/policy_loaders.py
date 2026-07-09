from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from medexa.regions.bundle import RegionBundle
from medexa.regions.policy_loader import load_policy_records


@dataclass(frozen=True)
class SaudiRequiredSessionFieldsLoader:
    bundle: RegionBundle

    def load(self) -> dict[str, Any]:
        records = load_policy_records(self.bundle.asset_path("pre_auth/required_session_fields.json"))
        return records[0] if records else {}


@dataclass(frozen=True)
class SaudiPreAuthServicesLoader:
    bundle: RegionBundle

    def load(self) -> list[dict[str, Any]]:
        return load_policy_records(self.bundle.asset_path("pre_auth/pre_auth_required_services.json"))


@dataclass(frozen=True)
class SaudiDocumentationRequirementsLoader:
    bundle: RegionBundle

    def load(self) -> list[dict[str, Any]]:
        return load_policy_records(self.bundle.asset_path("rules/documentation_requirements.json"))
