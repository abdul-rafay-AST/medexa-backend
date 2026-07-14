from __future__ import annotations

from pathlib import Path
from typing import Any

from medexa.domain.billing_region import BillingRegion, normalize_billing_region
from medexa.regions.bundle import RegionBundle
from medexa.regions.profile_loader import load_region_profile
from medexa.regions.storage import RegionAssetPaths
from medexa.regions.us.bundle import build_us_bundle
from medexa.regions.sa.bundle import build_sa_bundle
from medexa.regions.ae.bundle import build_ae_bundle


class RegionRegistry:
    """Factory for region bundles.

    Phase 0/1 ships a fully wired US bundle plus validated placeholders for
    Saudi Arabia and UAE so the session contract and storage model are ready
    before region-specific rules land.
    """

    def __init__(
        self,
        config_root: Path,
        cpt_files_dir: Path,
        *,
        s3_loader: Any = None,
    ) -> None:
        self._config_root = config_root
        self._cpt_files_dir = cpt_files_dir
        self._s3_loader = s3_loader
        self._cache: dict[BillingRegion, RegionBundle] = {}

    def resolve(self, billing_region: BillingRegion | str | None) -> RegionBundle:
        normalized = normalize_billing_region(billing_region)
        cached = self._cache.get(normalized)
        if cached is not None:
            return cached
        bundle = self._build(normalized)
        self._cache[normalized] = bundle
        return bundle

    def _build(self, billing_region: BillingRegion) -> RegionBundle:
        if billing_region == "US":
            return build_us_bundle(self._config_root, self._cpt_files_dir)
        if billing_region == "SA":
            return build_sa_bundle(self._config_root, self._cpt_files_dir)
        if billing_region == "AE":
            return build_ae_bundle(self._config_root, self._cpt_files_dir)
        region_dir = self._config_root / "regions" / billing_region.lower()
        if not region_dir.exists():
            raise ValueError(f"Region assets are not configured for {billing_region}")
        # Phase 0 validates the profile and directory structure even before the
        # region-specific rule implementations are available.
        return RegionBundle(
            billing_region=billing_region,
            profile=load_region_profile(region_dir / "region_profile.json"),
            asset_paths=RegionAssetPaths(
                config_root=self._config_root,
                region_dir=region_dir,
                legacy_fallbacks={},
                s3_loader=self._s3_loader,
            ),
            cpt_files_dir=self._cpt_files_dir,
        )
