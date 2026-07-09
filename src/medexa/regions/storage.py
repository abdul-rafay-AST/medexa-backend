from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RegionAssetPaths:
    """Resolves region assets with an explicit legacy fallback map.

    Phase 1 keeps the current US files working while we introduce the
    ``config/regions/<region>/`` layout. Once files are fully moved, the legacy
    fallback map can be deleted without touching the application layer.
    """

    config_root: Path
    region_dir: Path
    legacy_fallbacks: dict[str, Path]

    def resolve(self, relative_path: str) -> Path:
        normalized = relative_path.replace("\\", "/").lstrip("/")
        candidate = self.region_dir / normalized
        if candidate.exists():
            return candidate
        legacy = self.legacy_fallbacks.get(normalized)
        if legacy is not None and legacy.exists():
            return legacy
        return candidate
