import json
from pathlib import Path

class ActivitySynonymLoader:
    def __init__(self, config_path: Path):
        self._synonym_map: dict[str, str] = {}
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        with open(config_path) as f:
            self._synonym_map = json.load(f)

    def get_activity_label(self, phrase: str) -> str | None:
        return self._synonym_map.get(phrase.lower())

    def find_matches(self, text_lower: str) -> list[tuple[str, str]]:
        """Return ``(matched_phrase, activity_label)`` for every synonym in the text."""
        return [
            (phrase, label)
            for phrase, label in self._synonym_map.items()
            if phrase in text_lower
        ]
