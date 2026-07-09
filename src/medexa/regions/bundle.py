from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from medexa.domain.billing_region import BillingRegion
from medexa.regions.profile_loader import RegionProfile
from medexa.regions.storage import RegionAssetPaths


@dataclass(frozen=True)
class RegionBundle:
    billing_region: BillingRegion
    profile: RegionProfile
    asset_paths: RegionAssetPaths
    cpt_files_dir: Path

    def asset_path(self, relative_path: str) -> Path:
        return self.asset_paths.resolve(relative_path)
