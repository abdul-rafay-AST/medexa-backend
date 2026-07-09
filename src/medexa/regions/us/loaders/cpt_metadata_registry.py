from __future__ import annotations

from medexa.loaders.hybrid_cpt_metadata_registry import HybridCptMetadataRegistry
from medexa.regions.bundle import RegionBundle


class UsCptMetadataRegistry(HybridCptMetadataRegistry):
    def __init__(self, bundle: RegionBundle) -> None:
        super().__init__(bundle.asset_paths.region_dir / "codes", bundle.cpt_files_dir)
