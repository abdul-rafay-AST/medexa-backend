import json
from pathlib import Path

class BodyRegionNormalizer:
    def __init__(self, config_path: Path):
        self._region_map: dict[str, str] = {}
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        with open(config_path, encoding="utf-8") as f:
            self._region_map = json.load(f)

    def normalize(self, phrase: str) -> str | None:
        return self._region_map.get(phrase.lower())

    def find_region(self, text_lower: str) -> str | None:
        """Return the first normalized body region mentioned in the text, if any."""
        for phrase, normalized in self._region_map.items():
            if phrase in text_lower:
                return normalized
        return None
