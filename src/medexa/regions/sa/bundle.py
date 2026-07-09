from __future__ import annotations

from pathlib import Path

from medexa.regions.bundle import RegionBundle
from medexa.regions.profile_loader import load_region_profile
from medexa.regions.storage import RegionAssetPaths


def build_sa_bundle(config_root: Path, cpt_files_dir: Path) -> RegionBundle:
    region_dir = config_root / "regions" / "sa"
    profile = load_region_profile(region_dir / "region_profile.json")
    gcc_body_regions = config_root / "regions" / "gcc" / "common" / "body_regions.json"
    return RegionBundle(
        billing_region="SA",
        profile=profile,
        asset_paths=RegionAssetPaths(
            config_root=config_root,
            region_dir=region_dir,
            legacy_fallbacks={
                "clinical/body_regions.json": gcc_body_regions,
            },
        ),
        cpt_files_dir=cpt_files_dir,
    )
