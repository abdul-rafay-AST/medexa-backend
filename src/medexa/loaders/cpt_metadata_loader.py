import json
from pathlib import Path
from typing import TypedDict


class CptMetadata(TypedDict):
    label: str
    display_name: str
    descriptor: str
    timed: bool
    confidence: str
    notes: str


class CptMetadataLoader:
    """Loads per-CPT metadata (descriptor, timed/untimed flag, display name).

    The ``timed`` flag is billing-critical: only timed codes flow through the
    CMS 8-minute rule; untimed modalities bill 1 unit per session.
    """

    def __init__(self, config_path: Path):
        self._meta: dict[str, CptMetadata] = {}
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        with open(config_path) as f:
            self._meta = json.load(f)

    def get(self, cpt_code: str) -> CptMetadata | None:
        return self._meta.get(cpt_code)

    def is_timed(self, cpt_code: str) -> bool:
        """Whether a CPT is time-based. Unknown codes default to timed=True
        (conservative: forces 8-minute-rule review rather than silently billing
        a flat unit for an unrecognized code)."""
        meta = self._meta.get(cpt_code)
        return bool(meta["timed"]) if meta is not None else True

    def get_display_name(self, cpt_code: str) -> str:
        meta = self._meta.get(cpt_code)
        return meta["display_name"] if meta is not None else cpt_code
