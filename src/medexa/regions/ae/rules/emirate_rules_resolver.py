from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from medexa.regions.ae.loaders.policy_loaders import UaeEmirateRoutingLoader
from medexa.regions.bundle import RegionBundle


@dataclass
class UaeEmirateRulesResolver:
    bundle: RegionBundle

    def __post_init__(self) -> None:
        self._routes = {
            str(item["emirate"]): item for item in UaeEmirateRoutingLoader(self.bundle).load()
        }

    def resolve(self, emirate: str | None) -> dict[str, Any] | None:
        if emirate is None:
            return None
        return self._routes.get(emirate)
