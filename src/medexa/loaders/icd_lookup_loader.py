from __future__ import annotations

import json
from pathlib import Path


class IcdLookupLoader:
    """Maps clinical phrases to ICD-10-CM codes (flat-file, in-memory).

    Matching is **longest-phrase-first** so that a specific mention such as
    ``"right knee osteoarthritis"`` wins over the generic ``"knee pain"``. This
    mirrors the deterministic, sub-second design of the CPT lookup and keeps the
    diagnosis layer fully rules-based (no LLM required for the MVP path).

    Metadata keys (anything beginning with ``_``, e.g. ``_sources``) are ignored.
    """

    def __init__(self, config_path: Path):
        self._icd_map: dict[str, str] = {}
        # Phrases sorted by descending length once, at load time, so per-chunk
        # matching is a single linear scan (no repeated sorting on the hot path).
        self._phrases_by_length: list[str] = []
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        with open(config_path, encoding="utf-8") as f:
            raw = json.load(f)
        self._icd_map = {
            phrase.lower(): code
            for phrase, code in raw.items()
            if not phrase.startswith("_") and isinstance(code, str)
        }
        self._phrases_by_length = sorted(self._icd_map, key=len, reverse=True)

    def get_code(self, phrase: str) -> str | None:
        return self._icd_map.get(phrase.lower())

    def find_matches(self, text_lower: str) -> list[tuple[str, str]]:
        """Return ``(matched_phrase, icd_code)`` for the longest, non-overlapping
        diagnosis phrases found in ``text_lower``.

        Overlap suppression prevents a contained phrase (``"knee pain"``) from
        also matching once its longer parent (``"right knee pain"``) has claimed
        that span of text.
        """
        matches: list[tuple[str, str]] = []
        claimed: list[tuple[int, int]] = []

        for phrase in self._phrases_by_length:
            start = text_lower.find(phrase)
            if start == -1:
                continue
            end = start + len(phrase)
            if any(start < c_end and c_start < end for c_start, c_end in claimed):
                continue
            claimed.append((start, end))
            matches.append((phrase, self._icd_map[phrase]))

        return matches
