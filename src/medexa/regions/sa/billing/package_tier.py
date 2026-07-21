"""Resolve OT/PT/SLP package child codes from ended contact duration.

Only real SBS children are returned (e.g. 98014-00-30). Prefixes like
98014- are recognition keys only — never billable codes.
"""

from __future__ import annotations

# Ceiling bands: (max_minutes inclusive, suffix). Order matters — first match wins.
# OT/PT half-day (>120 and <240) and full-day (>=240) use explicit branches below.
_MINUTE_CEILINGS: list[tuple[float, str]] = [
    (15.0, "10"),
    (30.0, "20"),
    (45.0, "30"),
    (60.0, "40"),
    (120.0, "50"),
]

_PACKAGE_STEMS: dict[str, str] = {
    "98010-": "98010-00-",
    "98014-": "98014-00-",
    "98016-": "98016-00-",
}

# Speech has no half-day / full-day children; cap at 120-min tier.
_SPEECH_PREFIX = "98016-"
_HALF_DAY_SUFFIX = "60"
_FULL_DAY_SUFFIX = "70"
_SPEECH_CAP_SUFFIX = "50"


def is_package_code(cpt_code: str) -> bool:
    code = (cpt_code or "").strip()
    return any(code.startswith(prefix) for prefix in _PACKAGE_STEMS)


def _package_stem(cpt_code: str) -> str | None:
    code = (cpt_code or "").strip()
    for prefix, stem in _PACKAGE_STEMS.items():
        if code.startswith(prefix):
            return stem
    return None


def resolve_package_tier(cpt_code: str, duration_minutes: float) -> str:
    """Map a package child + ended duration to the correct existing child code.

    Non-package codes are returned unchanged. Duration matching upgrades or
    downgrades within the same package prefix so the billed code matches contact time.
    """
    code = (cpt_code or "").strip()
    stem = _package_stem(code)
    if stem is None:
        return code

    minutes = max(0.0, float(duration_minutes))

    for ceiling, suffix in _MINUTE_CEILINGS:
        if minutes <= ceiling:
            return f"{stem}{suffix}"

    # Beyond 120 minutes
    if code.startswith(_SPEECH_PREFIX):
        return f"{stem}{_SPEECH_CAP_SUFFIX}"

    if minutes < 240.0:
        return f"{stem}{_HALF_DAY_SUFFIX}"
    return f"{stem}{_FULL_DAY_SUFFIX}"
