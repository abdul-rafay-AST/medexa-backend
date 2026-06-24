import json
from pathlib import Path

class CptLookupLoader:
    def __init__(self, config_path: Path):
        self._cpt_map: dict[str, str] = {}
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        with open(config_path, encoding="utf-8") as f:
            self._cpt_map = json.load(f)

    def get_cpt_for_activity(self, activity_label: str) -> str | None:
        return self._cpt_map.get(activity_label)
