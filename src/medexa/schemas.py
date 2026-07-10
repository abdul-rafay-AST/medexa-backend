from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from medexa.domain.assistant_suggestion import AssistantSuggestion
from medexa.domain.billing_region import BillingRegion, DEFAULT_BILLING_REGION
from medexa.domain.audit import ComplianceAuditEntry
from medexa.domain.documentation_review import DocumentationReviewReport
from medexa.domain.pre_authorization import PreAuthSnapshot
from medexa.domain.fhir_export import FhirExportArtifact, PreAuthReconciliationReport
from medexa.domain.transcript_timeline import TimelineEvent
from medexa.utils.time import now_utc

Confidence = Literal["low", "medium", "high"]


class TranscriptChunk(BaseModel):
    session_id: str
    chunk_id: str
    text: str
    start_ts: float
    end_ts: float
    sequence: int
    speaker_role: Literal["therapist", "patient"] | None = None


class TranscriptUtterance(BaseModel):
    """One diarized ambient speech segment with clinical speaker role."""

    utterance_id: str
    speaker: Literal["therapist", "patient"]
    text: str
    start_ts: float
    end_ts: float
    confidence: float = 0.5
    source_chunk_id: str
    diarization_method: Literal["voice", "text", "hybrid", "deepgram"] | None = None


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
    policy_id: str | None = None
    rule_id: str | None = None
    cpt_codes: list[str] = Field(default_factory=list)
    body_region: str | None = None
    status: Literal["open", "approved", "rejected", "ignored"] = "open"
    source_chunk_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc)


# ---------------------------------------------------------------------------
# Clinical analysis (produced by the swappable ClinicalAnalyzer service).
#
# These are the *domain* representations of the rich, frontend-facing clinical
# output. They are deliberately decoupled from the HTTP contract (see
# ``medexa.api.contracts``) so the engine never depends on the wire format.
# ---------------------------------------------------------------------------
class IcdSuggestion(BaseModel):
    phrase: str
    code: str
    reason: str
    confidence: Confidence = "medium"


class BodyRegionMention(BaseModel):
    phrase: str
    region: str


class CptSuggestionDetail(BaseModel):
    code: str
    label: str
    display_name: str
    descriptor: str
    matched_phrases: list[str] = Field(default_factory=list)
    documentation_requirements: list[str] = Field(default_factory=list)
    billing_caveats: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    confidence: Confidence = "high"


class NcciConflictDetail(BaseModel):
    cpt_a: str
    cpt_b: str
    conflict_type: str
    body_region_sensitive: bool
    modifier_59_possible: bool
    explanation: str
    severity: Literal["info", "warning"] = "warning"


class SoapUpdate(BaseModel):
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""


class ClinicalAnalysis(BaseModel):
    """Full clinical interpretation of a transcript segment. The live billing
    rules engine continues to run alongside this; this object adds the
    diagnosis/ICD/SOAP layer the frontend documentation screens consume."""

    summary: str = ""
    possible_clinical_impressions: list[str] = Field(default_factory=list)
    possible_diagnoses: list[str] = Field(default_factory=list)
    icd10_suggestions: list[IcdSuggestion] = Field(default_factory=list)
    body_regions: list[BodyRegionMention] = Field(default_factory=list)
    cpt_suggestions: list[CptSuggestionDetail] = Field(default_factory=list)
    ncci_conflicts: list[NcciConflictDetail] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    soap_update: SoapUpdate = Field(default_factory=SoapUpdate)
    billing_hints: list[str] = Field(default_factory=list)
    confidence: Confidence = "low"
    disclaimer: str = "AI-generated suggestions require clinician review before use."


# ---------------------------------------------------------------------------
# Documentation aggregate (SOAP note, patient summary, claim, billing review).
# Stored on the session so post-session screens are server-authoritative.
# ---------------------------------------------------------------------------
class ProtocolInsight(BaseModel):
    insight_id: str
    type: Literal["protocol", "detected", "billing"]
    label: str
    question: str
    description: str
    status: Literal["pending", "approved", "ignored"] = "pending"


class SoapSubjective(BaseModel):
    chief_complaint: str = ""
    pain_scale: str = ""
    duration: str = ""


class SoapObjective(BaseModel):
    observation_notes: str = ""
    range_of_motion: str = ""
    affect: str = ""
    vital_signs: str = ""


class SoapAssessment(BaseModel):
    diagnosis_summary: str = ""
    primary_diagnosis_code: str = ""
    severity: str = ""


class SoapPlan(BaseModel):
    follow_up_plan: str = ""


class SoapBillingDocumentation(BaseModel):
    """RCM-facing intervention and coding context — sourced from Path A + transcript."""

    intervention_blocks: list[str] = Field(default_factory=list)
    cpt_summary: list[str] = Field(default_factory=list)
    ncci_alerts: list[str] = Field(default_factory=list)
    compliance_gaps: list[str] = Field(default_factory=list)
    total_session_minutes: int | None = None


class SoapNote(BaseModel):
    subjective: SoapSubjective = Field(default_factory=SoapSubjective)
    objective: SoapObjective = Field(default_factory=SoapObjective)
    assessment: SoapAssessment = Field(default_factory=SoapAssessment)
    plan: SoapPlan = Field(default_factory=SoapPlan)
    billing_documentation: SoapBillingDocumentation = Field(default_factory=SoapBillingDocumentation)
    generated: bool = False


class PatientSummaryDoc(BaseModel):
    summary: str = ""
    sent: bool = False


class ClaimLineItem(BaseModel):
    line_id: str
    code: str
    description: str
    units: str
    duration: str
    modifier: str = ""


class ClaimDiagnosis(BaseModel):
    diagnosis_id: str
    code: str
    description: str
    type: Literal["Primary", "Secondary"] = "Secondary"


class ClaimDoc(BaseModel):
    provider: str | None = None
    payor: str | None = None
    session_label: str | None = None
    extra_line_items: list[ClaimLineItem] = Field(default_factory=list)
    diagnoses: list[ClaimDiagnosis] = Field(default_factory=list)
    status: Literal["draft", "verified", "submitted"] = "draft"


class BillingReviewItem(BaseModel):
    """Human-review overrides layered on top of the rules-derived billing.

    ``manual`` line items are clinician-added codes not detected by the engine.
    """

    cpt_code: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    note: str | None = None
    warning: str | None = None
    manual: bool = False
    title: str | None = None
    units: str | None = None
    duration: str | None = None


class PatientDisplay(BaseModel):
    """Non-clinical display metadata echoed back to the dashboard. Held
    verbatim from the start-session payload; never used in billing logic."""

    avatar: str = ""
    age_sex: str = ""
    weight: str = ""
    payor_source: str = ""
    care_type: str = ""
    cpt: str = ""
    icd: str = ""
    session_time: str = ""
    date_time: str = ""


class PathBTriggerRecord(BaseModel):
    trigger_id: str
    session_id: str
    reason: str
    source_event_type: str
    status: Literal["pending", "dispatched", "completed", "skipped"] = "pending"
    created_at: datetime = Field(default_factory=now_utc)


class SessionState(BaseModel):
    session_id: str
    billing_region: BillingRegion = DEFAULT_BILLING_REGION
    emirate: Literal["DHA", "DOH", "MOHAP"] | None = None
    patient_id: str | None = None
    patient_name: str | None = None
    mrn: str | None = None
    therapist_id: str | None = None
    session_type: str | None = None
    payer_id: str | None = None
    member_id: str | None = None
    pre_auth_reference: str | None = None
    pre_auth_snapshot: PreAuthSnapshot | None = None
    pre_auth_reconciliation: PreAuthReconciliationReport | None = None
    documentation_review: DocumentationReviewReport | None = None
    fhir_export: FhirExportArtifact | None = None
    active_cpt: str | None = None
    active_body_region: str | None = None
    is_currently_billable: bool = False
    timer_segments: list[TimerSegment] = Field(default_factory=list)
    detected_entities: list[DetectedEntity] = Field(default_factory=list)
    transcript_chunks: list[TranscriptChunk] = Field(default_factory=list)
    transcript_utterances: list[TranscriptUtterance] = Field(default_factory=list)
    last_ambient_speaker: Literal["therapist", "patient"] | None = None
    ambient_voice_centroids: dict[str, list[float]] = Field(default_factory=dict)
    ambient_voice_pitch_centroids: dict[str, float] = Field(default_factory=dict)
    ambient_voice_cluster_roles: dict[str, Literal["therapist", "patient"]] = Field(default_factory=dict)
    ambient_deepgram_speaker_roles: dict[str, Literal["therapist", "patient"]] = Field(
        default_factory=dict
    )
    last_voice_cluster: str | None = None
    last_ambient_pitch_hz: float | None = None
    timeline_events: list[TimelineEvent] = Field(default_factory=list)
    audit_log: list[ComplianceAuditEntry] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
    status: Literal["active", "paused", "ended"] = "active"
    finalized_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)
    last_updated: datetime = Field(default_factory=now_utc)

    # --- Frontend-facing aggregate (additive; defaults keep engine/tests intact) ---
    patient_display: PatientDisplay = Field(default_factory=PatientDisplay)
    transcript_text: str = ""
    transcript_summary: str | None = None
    client_elapsed_seconds: int | None = None
    latest_analysis: ClinicalAnalysis | None = None
    insights: list[ProtocolInsight] = Field(default_factory=list)
    soap: SoapNote = Field(default_factory=SoapNote)
    patient_summary: PatientSummaryDoc = Field(default_factory=PatientSummaryDoc)
    claim: ClaimDoc = Field(default_factory=ClaimDoc)
    billing_review: list[BillingReviewItem] = Field(default_factory=list)
    path_b_triggers: list[PathBTriggerRecord] = Field(default_factory=list)
    assistant_suggestions: list[AssistantSuggestion] = Field(default_factory=list)
    cpt_timer_source: Literal["manual", "ai_suggested"] | None = None
    cpt_timer_reason: str | None = None


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