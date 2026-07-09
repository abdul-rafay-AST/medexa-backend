from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from medexa.utils.time import now_utc


class AuditAction(str, Enum):
    """Immutable compliance actions — HIPAA/billing defensibility."""

    CHUNK_INGESTED = "chunk_ingested"
    INSIGHT_APPROVED = "insight_approved"
    INSIGHT_IGNORED = "insight_ignored"
    SUGGESTION_APPLIED = "suggestion_applied"
    SUGGESTION_DISMISSED = "suggestion_dismissed"
    ALERT_APPROVED = "alert_approved"
    ALERT_REJECTED = "alert_rejected"
    SESSION_FINALIZED = "session_finalized"
    FHIR_EXPORTED = "fhir_exported"
    ASSISTANT_SUGGESTION_CREATED = "assistant_suggestion_created"


class ComplianceAuditEntry(BaseModel):
    """Value object: one clinician or system decision on a session."""

    entry_id: str
    session_id: str
    action: AuditAction
    actor: Literal["clinician", "system"] = "system"
    target_id: str | None = None
    detail: str = ""
    recorded_at: datetime = Field(default_factory=now_utc)

    model_config = {"frozen": True}
