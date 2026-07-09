from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict


class CptMetadataRecord(TypedDict, total=False):
    label: str
    display_name: str
    descriptor: str
    timed: bool
    confidence: str
    clinical_rationale: str
    documentation_requirements: list[str]
    billing_caveats: dict[str, Any]
    notes: str


class HybridCptMetadataRegistry:
    """Facade over rich legacy metadata + CMS general info (hybrid strategy)."""

    def __init__(self, config_dir: Path, cpt_files_dir: Path) -> None:
        self._meta: dict[str, CptMetadataRecord] = {}
        self._load_rich(config_dir / "cpt_metadata.json")
        general = cpt_files_dir / "cpt_general_info_filtered.json"
        if general.exists():
            self._overlay_general(general)

    @staticmethod
    def _is_meta_key(key: str) -> bool:
        return key.startswith("_")

    def _load_rich(self, path: Path) -> None:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        for code, record in data.items():
            if self._is_meta_key(code) or not isinstance(record, dict):
                continue
            self._meta[code] = record  # type: ignore[assignment]

    def _overlay_general(self, path: Path) -> None:
        rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            code = row.get("cpt_code")
            if not code or code in self._meta:
                continue
            self._meta[code] = {
                "label": code,
                "display_name": row.get("description", code),
                "descriptor": row.get("description", ""),
                "timed": bool(row.get("isEightMinuteRule", True)),
                "confidence": "medium",
                "notes": "Imported from CMS general info (hybrid overlay).",
            }

    def get(self, cpt_code: str) -> dict[str, Any] | None:
        from typing import cast
        return cast(dict[str, Any], self._meta.get(cpt_code))

    def is_timed(self, cpt_code: str) -> bool:
        meta = self._meta.get(cpt_code)
        return bool(meta["timed"]) if meta is not None else True

    def get_display_name(self, cpt_code: str) -> str:
        meta = self._meta.get(cpt_code)
        if meta is None:
            return cpt_code
        return meta.get("display_name") or meta.get("label") or cpt_code
