from __future__ import annotations

from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.regions.bundle import RegionBundle


class UsBodyRegionNormalizer(BodyRegionNormalizer):
    def __init__(self, bundle: RegionBundle) -> None:
        super().__init__(bundle.asset_path("clinical/body_regions.json"))
