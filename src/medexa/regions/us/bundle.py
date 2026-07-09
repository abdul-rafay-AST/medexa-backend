from __future__ import annotations

from pathlib import Path

from medexa.regions.bundle import RegionBundle
from medexa.regions.profile_loader import load_region_profile
from medexa.regions.storage import RegionAssetPaths


def build_us_bundle(config_root: Path, cpt_files_dir: Path) -> RegionBundle:
    region_dir = config_root / "regions" / "us"
    profile = load_region_profile(region_dir / "region_profile.json")
    return RegionBundle(
        billing_region="US",
        profile=profile,
        asset_paths=RegionAssetPaths(
            config_root=config_root,
            region_dir=region_dir,
            legacy_fallbacks={
                "codes/cpt_lookup.json": config_root / "cpt_lookup.json",
                "codes/cpt_metadata.json": config_root / "cpt_metadata.json",
                "codes/icd_lookup.json": config_root / "icd_lookup.json",
                "codes/activity_synonyms.json": config_root / "activity_synonyms.json",
                "rules/ncci_rules.json": config_root / "ncci_rules.json",
                "clinical/body_regions.json": config_root / "body_regions.json",
            },
        ),
        cpt_files_dir=cpt_files_dir,
    )
