"""Human-readable labels for normalized body region codes."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_REGION_CONFIG = (
    Path(__file__).resolve().parents[3] / "config" / "regions" / "us" / "clinical" / "body_regions.json"
)


@lru_cache(maxsize=1)
def _display_map() -> dict[str, str]:
    with open(_REGION_CONFIG, encoding="utf-8") as f:
        phrase_to_code: dict[str, str] = json.load(f)
    display: dict[str, str] = {}
    for phrase, code in phrase_to_code.items():
        if code not in display:
            display[code] = phrase.title()
    return display


def body_region_display(code: str | None) -> str | None:
    """Map ``shoulder_right`` → ``Right Shoulder`` using clinical phrase catalog."""
    if not code:
        return None
    return _display_map().get(code, code.replace("_", " ").title())
