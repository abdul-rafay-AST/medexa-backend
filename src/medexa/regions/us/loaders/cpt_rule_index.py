from __future__ import annotations

from medexa.loaders.hybrid_cpt_rule_index import HybridCptRuleIndex
from medexa.regions.bundle import RegionBundle


class UsCptRuleIndex(HybridCptRuleIndex):
    def __init__(self, bundle: RegionBundle) -> None:
        super().__init__(bundle.asset_paths.region_dir / "codes", bundle.cpt_files_dir)
