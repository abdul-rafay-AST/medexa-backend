from __future__ import annotations

from medexa.loaders.icd_lookup_loader import IcdLookupLoader
from medexa.regions.bundle import RegionBundle


class UsIcdLookupLoader(IcdLookupLoader):
    def __init__(self, bundle: RegionBundle) -> None:
        super().__init__(bundle.asset_path("codes/icd_lookup.json"))
