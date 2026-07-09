"""HTTP wire contracts mirroring the frontend's ``src/lib/api.ts`` types.

These models are the **anti-corruption boundary**: the domain (``medexa.schemas``)
stays clean and the engine never depends on the frontend's field naming. Two
casing conventions are intentional, matching the frontend verbatim:

* Resource models (sessions, billing, claims, SOAP) are **camelCase** — emitted
  via a Pydantic alias generator. FastAPI serializes responses ``by_alias=True``.
* Clinical-analysis payloads are **snake_case** — the frontend declares those
  keys in snake_case (``possible_diagnoses``, ``cpt_suggestions``, ...).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for camelCase wire models. Accepts snake_case on input (so routers
    can build them naturally) and emits camelCase on output."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


RecordingStatus = Literal["idle", "recording", "paused", "stopped"]
Confidence = Literal["low", "medium", "high"]


# ---------------------------------------------------------------------------
# Sessions & recording state
# ---------------------------------------------------------------------------
class ApiSession(CamelModel):
    id: str
    billing_region: Literal["US", "SA", "AE"] = "US"
    emirate: Literal["DHA", "DOH", "MOHAP"] | None = None
    payer_id: str | None = None
    member_id: str | None = None
    pre_auth_reference: str | None = None
    patient_name: str = ""
    avatar: str = ""
    age_sex: str = ""
    weight: str = ""
    mrn_number: str = ""
    payor_source: str = ""
    care_type: str = ""
    cpt: str = ""
    icd: str = ""
    session_time: str = ""
    status: str = "Scheduled"
    date_time: str = ""


class ApiRecordingState(CamelModel):
    status: RecordingStatus
    elapsed_seconds: int = 0
    billing_elapsed_seconds: int = 0
    cpt_elapsed_seconds: int = 0
    units: int = 0
    next_unit_at: int = 0
    time_left: int = 0


class StartSessionResponse(CamelModel):
    session: ApiSession
    state: ApiRecordingState


class StartSessionRequest(CamelModel):
    # Frontend posts a patient-shaped object; all fields optional. Unknown keys
    # are ignored rather than rejected (forward-compatible with UI changes).
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    id: str | None = None
    patient_id: str | None = None
    patient_name: str | None = None
    avatar: str | None = None
    age_sex: str | None = None
    weight: str | None = None
    mrn_number: str | None = None
    mrn: str | None = None
    payor_source: str | None = None
    care_type: str | None = None
    cpt: str | None = None
    icd: str | None = None
    session_time: str | None = None
    date_time: str | None = None
    therapist_id: str | None = None
    session_type: str | None = None
    billing_region: Literal["US", "SA", "AE"] | None = None
    emirate: Literal["DHA", "DOH", "MOHAP"] | None = None
    payer_id: str | None = None
    member_id: str | None = None
    pre_auth_reference: str | None = None


class UpdateRecordingStateRequest(CamelModel):
    status: RecordingStatus
    elapsed_seconds: int | None = None


# ---------------------------------------------------------------------------
# Transcripts (recordings list)
# ---------------------------------------------------------------------------
class ApiTranscript(CamelModel):
    id: str
    patient_name: str = ""
    avatar: str = ""
    time: str = ""
    status: Literal["SUMMARIZED", "SUMMARY PENDING"] = "SUMMARY PENDING"
    summary: str = ""
    transcript: str = ""


# ---------------------------------------------------------------------------
# Live insights & suggestions
# ---------------------------------------------------------------------------
class ApiInsight(CamelModel):
    id: str
    type: Literal["protocol", "detected", "billing"]
    label: str
    question: str
    description: str
    status: Literal["pending", "approved", "ignored"] = "pending"


class ApiSuggestion(CamelModel):
    id: str
    title: str
    text: str
    applied: bool = False


class ApiAssistantSuggestion(CamelModel):
    id: str
    trigger_id: str
    kind: Literal[
        "documentation_reminder",
        "missing_information",
        "clinical_question",
        "general",
    ] = "general"
    title: str
    body: str
    confidence: Confidence = "medium"
    status: Literal["active", "dismissed"] = "active"
    disclaimer: str = "AI-generated suggestions require clinician review before use."
    created_at: str = ""


# ---------------------------------------------------------------------------
# Clinical analysis (snake_case payloads)
# ---------------------------------------------------------------------------
class ApiIcd10Suggestion(BaseModel):
    phrase: str
    code: str
    reason: str
    confidence: Confidence


class ApiBodyRegion(BaseModel):
    phrase: str
    region: str


class ApiCptSuggestion(BaseModel):
    code: str
    label: str
    display_name: str
    descriptor: str
    matched_phrases: list[str] = []
    documentation_requirements: list[str] = []
    billing_caveats: dict[str, Any] = {}
    reason: str
    confidence: Confidence


class ApiNcciConflict(BaseModel):
    cpt_a: str
    cpt_b: str
    conflict_type: str
    body_region_sensitive: bool
    modifier_59_possible: bool
    explanation: str
    severity: Literal["info", "warning"]


class ApiSoapUpdate(BaseModel):
    subjective: str
    objective: str
    assessment: str
    plan: str


class ApiCptTimerSuggestion(BaseModel):
    should_start: bool = False
    code: str | None = None
    display_name: str | None = None
    reason: str = ""
    confidence: Confidence = "medium"


class ApiLiveSuggestion(BaseModel):
    id: str
    type: Literal["billing", "protocol", "detected", "alert"]
    title: str
    description: str
    action_label: str = "Review"
    status: Literal["pending", "applied", "ignored"] = "pending"


class ApiTranscriptAnalysis(BaseModel):
    summary: str
    possible_clinical_impressions: list[str] = []
    possible_diagnoses: list[str] = []
    icd10_suggestions: list[ApiIcd10Suggestion] = []
    body_regions: list[ApiBodyRegion] = []
    cpt_suggestions: list[ApiCptSuggestion] = []
    ncci_conflicts: list[ApiNcciConflict] = []
    symptoms: list[str] = []
    soap_update: ApiSoapUpdate
    billing_hints: list[str] = []
    confidence: Confidence
    disclaimer: str
    cpt_timer_suggestion: ApiCptTimerSuggestion | None = None
    live_suggestions: list[ApiLiveSuggestion] = []


class ApiAudioSegment(BaseModel):
    start: float
    end: float
    text: str


class ApiAudioTranscriptionAnalysis(ApiTranscriptAnalysis):
    transcript: str
    audio_segments: list[ApiAudioSegment] = []


class AnalyzeTranscriptChunkRequest(BaseModel):
    chunk_text: str
    start_time: str = ""
    end_time: str = ""
    # Simulated session clock (seconds since session start). Preferred for step-by-step testing.
    elapsed_seconds: int | None = None
    duration_seconds: int = 15


class ApiPathBTriggerStatus(CamelModel):
    id: str
    reason: str
    status: Literal["pending", "dispatched", "completed", "skipped"] = "pending"
    created_at: str = ""


class ApiPathAStatus(CamelModel):
    status: str = "live"
    entity_count: int = 0
    alert_count: int = 0
    suggestion_count: int = 0
    active_cpt: str | None = None
    cpt_display_name: str | None = None
    session_timer_sec: int = 0
    cpt_elapsed_seconds: int = 0
    units: int = 0


class ApiPathBStatus(CamelModel):
    enabled: bool = False
    status: str = "disabled"
    trigger_count: int = 0
    suggestion_count: int = 0
    triggers: list[ApiPathBTriggerStatus] = []


class ApiPathCStatus(CamelModel):
    status: str = "pending"
    has_soap: bool = False
    has_summary: bool = False
    review_open_count: int = 0


class ApiExtractedEntity(CamelModel):
    id: str
    phrase: str
    region: str | None = None
    cpt: str | None = None
    icd10: str | None = None
    is_billable: bool = False


class ApiLivePipelineSnapshot(CamelModel):
    """Single pollable view of Path A / B / C status for local testing UIs."""

    session_id: str
    billing_region: str = "US"
    elapsed_seconds: int = 0
    path_a: ApiPathAStatus = ApiPathAStatus()
    path_b: ApiPathBStatus = ApiPathBStatus()
    path_c: ApiPathCStatus = ApiPathCStatus()
    insights: list[ApiInsight] = []
    billing_suggestions: list[ApiSuggestion] = []
    assistant_suggestions: list[ApiAssistantSuggestion] = []
    entities: list[ApiExtractedEntity] = []
    transcript_preview: str = ""


# ---------------------------------------------------------------------------
# Session timers (snake_case — matches frontend ``api.ts`` timer types)
# ---------------------------------------------------------------------------
class ApiCptTimerState(BaseModel):
    active: bool = False
    code: str | None = None
    seconds: int = 0
    units: int = 0
    next_unit_at_seconds: int = 8 * 60
    seconds_left_to_next_unit: int = 8 * 60
    status: Literal["idle", "running", "paused", "stopped"] = "idle"
    source: Literal["manual", "ai_suggested"] | None = None
    reason: str | None = None


class ApiTimerState(BaseModel):
    session_id: str
    recording_status: RecordingStatus
    total_seconds: int
    cpt_timer: ApiCptTimerState


class StartCptTimerRequest(BaseModel):
    code: str
    source: Literal["manual", "ai_suggested"] = "manual"
    reason: str = ""


class FinalizeSessionRequest(BaseModel):
    transcript: str = ""
    total_seconds: int = 0
    cpt_timer: dict[str, Any] = {}
    applied_suggestions: list[str] = []
    detected_cpt_suggestions: list[ApiCptSuggestion] = []
    detected_icd10_suggestions: list[ApiIcd10Suggestion] = []
    ncci_conflicts: list[ApiNcciConflict] = []


# ---------------------------------------------------------------------------
# SOAP documentation
# ---------------------------------------------------------------------------
class SoapSubjectiveDTO(CamelModel):
    chief_complaint: str = ""
    pain_scale: str = ""
    duration: str = ""


class SoapObjectiveDTO(CamelModel):
    observation_notes: str = ""
    range_of_motion: str = ""
    affect: str = ""
    vital_signs: str = ""


class SoapAssessmentDTO(CamelModel):
    diagnosis_summary: str = ""
    primary_diagnosis_code: str = ""
    severity: str = ""


class SoapPlanDTO(CamelModel):
    follow_up_plan: str = ""


class SoapDataDTO(CamelModel):
    subjective: SoapSubjectiveDTO = SoapSubjectiveDTO()
    objective: SoapObjectiveDTO = SoapObjectiveDTO()
    assessment: SoapAssessmentDTO = SoapAssessmentDTO()
    plan: SoapPlanDTO = SoapPlanDTO()


class FhirExportSummary(CamelModel):
    profile_id: str
    bundle_id: str
    storage_uri: str | None = None
    storage_key: str | None = None
    byte_size: int = 0
    checksum_sha256: str | None = None
    exported_at: str = ""


class PreAuthReconciliationSummary(CamelModel):
    reconciled: bool = False
    snapshot_status: str | None = None
    pre_auth_reference: str | None = None
    open_violation_count: int = 0


class ApiDocumentationReviewItem(CamelModel):
    id: str
    category: Literal[
        "ncci",
        "units",
        "pre_auth",
        "documentation",
        "assistant_hint",
        "billing",
    ]
    severity: Literal["info", "warning", "high"]
    title: str
    detail: str
    resolved: bool = False


class ApiDocumentationReview(CamelModel):
    session_id: str
    items: list[ApiDocumentationReviewItem] = []
    open_count: int = 0
    generated_at: str = ""


class DocumentationReviewSummary(CamelModel):
    open_count: int = 0
    item_count: int = 0


class FinalizeSessionResponse(CamelModel):
    session_id: str
    soap_note: SoapDataDTO
    summary: str
    billing_summary: dict[str, Any]
    redirect_url: str
    fhir_export: FhirExportSummary | None = None
    pre_auth_reconciliation: PreAuthReconciliationSummary | None = None
    documentation_review: DocumentationReviewSummary | None = None


class PatientSummaryDTO(CamelModel):
    summary: str = ""
    sent: bool = False


class UpdatePatientSummaryRequest(CamelModel):
    summary: str


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
class ApiBillingCpt(CamelModel):
    id: str
    code: str
    title: str
    units: str
    duration: str
    warning: str = ""
    note: str | None = None
    status: Literal["pending", "approved", "rejected"] = "pending"


class ApiSnfFunctionalLogic(CamelModel):
    section: str
    level: str


class ApiBilling(CamelModel):
    session_time: str
    units: str
    threshold: str
    cpt_codes: list[ApiBillingCpt] = []
    snf_functional_logic: ApiSnfFunctionalLogic


class AddBillingCptRequest(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    code: str
    title: str | None = None
    units: str | None = None
    duration: str | None = None
    note: str | None = None
    warning: str | None = None


class EditBillingCptRequest(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    code: str | None = None
    title: str | None = None
    units: str | None = None
    duration: str | None = None
    note: str | None = None
    warning: str | None = None
    status: Literal["pending", "approved", "rejected"] | None = None


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
class ApiPatientMeta(CamelModel):
    patient: str = ""
    mrn: str = ""
    provider: str = ""
    session: str = ""
    payor: str = ""


class ApiClaimCpt(CamelModel):
    id: str
    code: str
    description: str
    units: str
    duration: str
    modifier: str = ""


class ApiClaimDiagnosis(CamelModel):
    id: str
    code: str
    description: str
    type: Literal["Primary", "Secondary"] = "Secondary"


class ApiClaim(CamelModel):
    patient_meta: ApiPatientMeta
    cpt_items: list[ApiClaimCpt] = []
    diagnosis_codes: list[ApiClaimDiagnosis] = []
    claim_status: Literal["draft", "verified", "submitted"] = "draft"


class AddClaimCptRequest(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    code: str
    description: str | None = None
    units: str | None = None
    duration: str | None = None
    modifier: str | None = None


class AddClaimDiagnosisRequest(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    code: str
    description: str | None = None
    type: Literal["Primary", "Secondary"] = "Secondary"
