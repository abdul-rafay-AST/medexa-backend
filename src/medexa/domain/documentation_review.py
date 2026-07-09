from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from medexa.utils.time import now_utc

ReviewCategory = Literal[
    "ncci",
    "units",
    "pre_auth",
    "documentation",
    "assistant_hint",
    "billing",
]
ReviewSeverity = Literal["info", "warning", "high"]


class DocumentationReviewItem(BaseModel):
    item_id: str
    category: ReviewCategory
    severity: ReviewSeverity
    title: str
    detail: str
    resolved: bool = False


class DocumentationReviewReport(BaseModel):
    session_id: str
    items: list[DocumentationReviewItem] = Field(default_factory=list)
    open_count: int = 0
    generated_at: datetime = Field(default_factory=now_utc)
