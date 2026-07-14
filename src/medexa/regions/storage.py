from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RegionAssetPaths:
    """Resolves region assets with S3 cache → local directory → legacy fallback.

    Resolution order:
      1. S3 cache (if an ``S3ConfigLoader`` was provided at construction)
      2. Local ``config/regions/<region>/`` directory
      3. Legacy fallback map (for backward-compatible file locations)
    """

    config_root: Path
    region_dir: Path
    legacy_fallbacks: dict[str, Path]
    s3_loader: Any = field(default=None, compare=False, hash=False)

    def resolve(self, relative_path: str) -> Path:
        normalized = relative_path.replace("\\", "/").lstrip("/")

        # 1. Try S3 cache first.
        if self.s3_loader is not None:
            billing_region = self.region_dir.name  # e.g. "us", "sa", "ae"
            s3_key = f"regions/{billing_region}/{normalized}"
            s3_path = self.s3_loader.resolve_path(s3_key)
            if s3_path is not None and s3_path.exists():
                return s3_path

        # 2. Try the local region directory.
        candidate = self.region_dir / normalized
        if candidate.exists():
            return candidate

        # 3. Try legacy fallback.
        legacy = self.legacy_fallbacks.get(normalized)
        if legacy is not None and legacy.exists():
            return legacy

        return candidate
