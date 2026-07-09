from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from medexa.utils.time import now_utc


class TimelineEvent(BaseModel):
    """Ordered session timeline entry for Path C and audit."""

    event_id: str
    session_id: str
    kind: Literal["chunk", "cpt_detected", "ncci_alert", "suggestion_applied", "insight_approved"]
    summary: str
    chunk_id: str | None = None
    cpt_code: str | None = None
    recorded_at: datetime = Field(default_factory=now_utc)
