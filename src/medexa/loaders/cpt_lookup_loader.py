import json
from pathlib import Path

class CptLookupLoader:
    """Legacy flat phrase loader — retained for scripts; runtime uses HybridCptRuleIndex."""

    def __init__(self, config_path: Path):
        self._cpt_map: dict[str, str] = {}
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        with open(config_path, encoding="utf-8") as f:
            raw = json.load(f)
        self._cpt_map = {k: v for k, v in raw.items() if not str(k).startswith("_")}

    def get_cpt_for_activity(self, activity_label: str) -> str | None:
        return self._cpt_map.get(activity_label)
