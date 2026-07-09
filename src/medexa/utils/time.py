from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Centralizing this avoids the deprecated ``datetime.utcnow()`` and prevents
    naive/aware datetime mixing (which raises on subtraction).
    """
    return datetime.now(timezone.utc)
