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

    def find_all_regions(self, text_lower: str) -> list[tuple[str, str]]:
        """Return ``(matched_phrase, normalized_region)`` for every distinct
        region mentioned in the text (first phrase wins per region)."""
        seen: set[str] = set()
        matches: list[tuple[str, str]] = []
        for phrase, normalized in self._region_map.items():
            if phrase in text_lower and normalized not in seen:
                seen.add(normalized)
                matches.append((phrase, normalized))
        return matches
