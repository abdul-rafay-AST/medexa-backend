from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from medexa.utils.time import now_utc


class TranscriptChunk(BaseModel):
    session_id: str
    chunk_id: str
    text: str
    start_ts: float
    end_ts: float
    sequence: int


class DetectedEntity(BaseModel):
    activity_label: str | None = None
    matched_phrase: str
    body_region: str | None = None
    timing_phrase: str | None = None
    is_billable: bool = False
    is_negated: bool = False
    possible_cpt: str | None = None
    source_chunk_id: str


class TimerSegment(BaseModel):
    segment_id: str
    cpt_code: str
    body_region: str | None = None
    start_time: datetime
    stop_time: datetime | None = None
    is_billable: bool = True
    accumulated_seconds: int = 0


class SuggestionAction(BaseModel):
    label: str
    action_type: Literal["apply", "set_duration", "note_it", "approve", "dismiss"]


class Suggestion(BaseModel):
    suggestion_id: str
    session_id: str
    source_chunk_id: str
    suggestion_type: Literal["cpt_apply", "action_note", "duration_entry"]
    title: str
    message: str
    cpt_code: str | None = None
    body_region: str | None = None
    proposed_duration_sec: int | None = None
    status: Literal["suggested", "applied", "dismissed", "expired"] = "suggested"
    actions: list[SuggestionAction] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now_utc)


class CurrentCptSnapshot(BaseModel):
    code: str
    label: str
    duration_sec: int
    body_region: str | None = None
    is_billable: bool = True
    status: Literal["in_progress", "paused", "stopped"]


class EightMinuteRuleResult(BaseModel):
    total_minutes: int
    total_units: int
    units_by_cpt: dict[str, int]
    minutes_by_cpt: dict[str, int]
    remainder_minutes: int
    remainder_assigned_to: str | None
    seconds_to_next_unit: int


class Alert(BaseModel):
    alert_id: str
    session_id: str
    alert_type: Literal["ncci_conflict", "missing_documentation", "timer_warning"]
    severity: Literal["low", "medium", "high"]
    message: str
    cpt_codes: list[str] = Field(default_factory=list)
    body_region: str | None = None
    status: Literal["open", "approved", "rejected", "ignored"] = "open"
    source_chunk_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


class SessionState(BaseModel):
    session_id: str
    patient_id: str | None = None
    patient_name: str | None = None
    mrn: str | None = None
    therapist_id: str | None = None
    session_type: str | None = None
    active_cpt: str | None = None
    active_body_region: str | None = None
    is_currently_billable: bool = False
    timer_segments: list[TimerSegment] = Field(default_factory=list)
    detected_entities: list[DetectedEntity] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    status: Literal["active", "paused", "ended"] = "active"
    created_at: datetime = Field(default_factory=now_utc)
    last_updated: datetime = Field(default_factory=now_utc)


class InsightsPanel(BaseModel):
    session_id: str
    current_cpt: CurrentCptSnapshot | None = None
    live_extractions: list[DetectedEntity] = Field(default_factory=list)
    eight_minute_rule: EightMinuteRuleResult | None = None
    alerts: list[Alert] = Field(default_factory=list)
    session_timer_sec: int
    last_updated: datetime = Field(default_factory=now_utc)


class BillingLineItem(BaseModel):
    cpt_code: str
    display_name: str
    timed: bool
    total_seconds: int
    units: int


class BillingSummary(BaseModel):
    session_id: str
    total_minutes: int
    total_units: int
    line_items: list[BillingLineItem] = Field(default_factory=list)
    eight_minute_rule: EightMinuteRuleResult | None = None
    alerts: list[Alert] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=now_utc)