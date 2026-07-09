from __future__ import annotations

from medexa.loaders.ncci_rules_loader import NcciRulesLoader
from medexa.regions.bundle import RegionBundle


class UsNcciRulesLoader(NcciRulesLoader):
    def __init__(self, bundle: RegionBundle) -> None:
        super().__init__(bundle.asset_path("rules/ncci_rules.json"))
