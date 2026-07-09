from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from medexa.utils.time import now_utc


class DomainEvent(BaseModel):
    session_id: str
    occurred_at: datetime = Field(default_factory=now_utc)
    event_type: str

    model_config = {"frozen": True}


class ChunkProcessed(DomainEvent):
    event_type: Literal["chunk_processed"] = "chunk_processed"
    chunk_id: str
    sequence: int
    entity_count: int
    suggestion_count: int


class ActivityChanged(DomainEvent):
    event_type: Literal["activity_changed"] = "activity_changed"
    activity_label: str
    cpt_code: str | None
    body_region: str | None


class BodyRegionChanged(DomainEvent):
    event_type: Literal["body_region_changed"] = "body_region_changed"
    body_region: str
    matched_phrase: str
    cpt_code: str | None = None


class CptDetected(DomainEvent):
    event_type: Literal["cpt_detected"] = "cpt_detected"
    cpt_code: str
    matched_phrase: str
    body_region: str | None = None


class DocumentationGapDetected(DomainEvent):
    event_type: Literal["documentation_gap_detected"] = "documentation_gap_detected"
    cpt_code: str
    missing_requirements: list[str]
    matched_phrase: str


class NcciConflictFound(DomainEvent):
    event_type: Literal["ncci_conflict_found"] = "ncci_conflict_found"
    cpt_a: str
    cpt_b: str
    severity: Literal["low", "medium", "high"] = "medium"


class PreAuthViolationFound(DomainEvent):
    event_type: Literal["pre_auth_violation_found"] = "pre_auth_violation_found"
    policy_id: str
    message: str
    severity: Literal["low", "medium", "high"] = "medium"
    service_category: str | None = None


class CodeConflictFound(DomainEvent):
    event_type: Literal["code_conflict_found"] = "code_conflict_found"
    rule_id: str
    message: str
    severity: Literal["low", "medium", "high"] = "medium"
    service_category: str | None = None


class PathAAlertRaised(DomainEvent):
    event_type: Literal["path_a_alert_raised"] = "path_a_alert_raised"
    alert_id: str
    alert_type: Literal[
        "ncci_conflict",
        "missing_documentation",
        "timer_warning",
        "pre_auth_required",
        "session_field_missing",
        "billing_conflict",
    ]
    severity: Literal["low", "medium", "high"]
    message: str
    cpt_codes: list[str] = Field(default_factory=list)


class PathBTriggerRequested(DomainEvent):
    event_type: Literal["path_b_trigger_requested"] = "path_b_trigger_requested"
    trigger_id: str
    reason: str
    source_event_type: str


class SessionEnded(DomainEvent):
    event_type: Literal["session_ended"] = "session_ended"
    total_chunks: int
    total_seconds: int
