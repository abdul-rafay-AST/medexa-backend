"""SBS display metadata implementing CptMetadataPort for SA Path A."""

from __future__ import annotations

from typing import Any

from medexa.regions.sa.detection.catalog import SaBillingCatalog

_TIMED_PREFIXES = ("98010-", "98014-", "98016-")


class SaSbsMetadataRegistry:
    """Expose SBS labels via the shared CPT metadata port interface."""

    def __init__(self, catalog: SaBillingCatalog) -> None:
        self._catalog = catalog

    def get(self, cpt_code: str) -> dict[str, Any] | None:
        entry = self._catalog.sbs_lookup.get(cpt_code)
        if entry is None and cpt_code not in self._catalog.sbs_labels:
            return None
        label = self._catalog.sbs_display_name(cpt_code)
        return {
            "label": label,
            "display_name": label,
            "descriptor": (entry or {}).get("notes") or "",
            "confidence": "high",
            "documentation_requirements": [],
            "billing_caveats": {},
            "timed": self.is_timed(cpt_code),
        }

    def is_timed(self, cpt_code: str) -> bool:
        return any(cpt_code.startswith(p) for p in _TIMED_PREFIXES)

    def get_display_name(self, cpt_code: str) -> str:
        return self._catalog.sbs_display_name(cpt_code)
