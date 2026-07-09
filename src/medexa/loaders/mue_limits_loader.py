from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


from typing import Any


@dataclass(frozen=True)
class MueLimit:
    cpt_code: str
    limit: int
    adjudication_level: str
    description: str


class MueLimitsLoader:
    """CMS Medically Unlikely Edits — loaded for future Path A alerts (Phase 6 ready)."""

    def __init__(self, cpt_files_dir: Path) -> None:
        self._limits: dict[str, MueLimit] = {}
        path = cpt_files_dir / "cpt_mue_info_filtered.json"
        if path.exists():
            self._load(path)

    def _load(self, path: Path) -> None:
        rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            code = row.get("cpt_code")
            mue = row.get("mue") or {}
            if not code:
                continue
            self._limits[code] = MueLimit(
                cpt_code=code,
                limit=int(mue.get("limit", 0)),
                adjudication_level=str(mue.get("adjudication_level", "")),
                description=str(mue.get("description", "")),
            )

    def get(self, cpt_code: str) -> MueLimit | None:
        return self._limits.get(cpt_code)
