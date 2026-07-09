from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from medexa.regions.ae.rules.emirate_rules_resolver import UaeEmirateRulesResolver
from medexa.regions.bundle import RegionBundle
from medexa.schemas import SessionState


@dataclass
class UaeEligibilityRouter:
    bundle: RegionBundle

    def __post_init__(self) -> None:
        self._resolver = UaeEmirateRulesResolver(self.bundle)

    def route(self, state: SessionState) -> dict[str, Any]:
        route = self._resolver.resolve(state.emirate)
        if route is None:
            return {
                "status": "unrouted",
                "reason": "emirate_missing_or_unsupported",
                "emirate": state.emirate,
            }
        return {
            "status": "routed",
            "emirate": state.emirate,
            "exchange_platform": route.get("exchange_platform"),
            "protocol_family": route.get("protocol_family"),
            "primary_identifiers": route.get("primary_identifiers", []),
        }
