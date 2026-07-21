"""Pure mapping functions between the domain (``medexa.schemas``) and the HTTP
contracts (``medexa.api.contracts``).

Keeping this logic in one dependency-free module means it is trivially unit
testable and the routers stay thin. No FastAPI, no I/O here.
"""

from __future__ import annotations

import hashlib

from medexa.api import contracts as c
from medexa.domain.assistant_suggestion import AssistantSuggestion
from medexa.domain.documentation_review import DocumentationReviewReport
from medexa.schemas import (
    BillingSummary,
    ClinicalAnalysis,
    ProtocolInsight,
    SessionState,
    SoapNote,
    Suggestion,
)


def format_mmss(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def recording_status(state: SessionState) -> c.RecordingStatus:
    return {"active": "recording", "paused": "paused", "ended": "stopped"}.get(
        state.status, "idle"
    )  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Sessions & recording state
# ---------------------------------------------------------------------------
def session_to_api(state: SessionState) -> c.ApiSession:
    d = state.patient_display
    return c.ApiSession(
        id=state.session_id,
        billing_region=state.billing_region,
        emirate=state.emirate,
        payer_id=state.payer_id,
        member_id=state.member_id,
        pre_auth_reference=state.pre_auth_reference,
        patient_name=state.patient_name or "",
        avatar=d.avatar,
        age_sex=d.age_sex,
        weight=d.weight,
        mrn_number=state.mrn or "",
        payor_source=d.payor_source,
        care_type=d.care_type or (state.session_type or ""),
        cpt=d.cpt,
        icd=d.icd,
        session_time=d.session_time,
        status="In Progress" if state.status == "active" else state.status.capitalize(),
        date_time=d.date_time,
    )


def recording_state(
    state: SessionState,
    *,
    elapsed_seconds: int,
    units: int,
    seconds_to_next_unit: int,
    billing_elapsed_seconds: int,
    cpt_elapsed_seconds: int,
) -> c.ApiRecordingState:
    wall = int(state.client_elapsed_seconds or 0)
    billing = billing_elapsed_seconds
    return c.ApiRecordingState(
        status=recording_status(state),
        elapsed_seconds=wall,
        billing_elapsed_seconds=billing,
        cpt_elapsed_seconds=cpt_elapsed_seconds,
        units=units,
        next_unit_at=billing + max(0, seconds_to_next_unit),
        time_left=max(0, seconds_to_next_unit),
    )


# ---------------------------------------------------------------------------
# Clinical analysis
# ---------------------------------------------------------------------------
def analysis_to_contract(
    a: ClinicalAnalysis,
    *,
    state: SessionState | None = None,
) -> c.ApiTranscriptAnalysis:
    base = c.ApiTranscriptAnalysis(
        summary=a.summary,
        possible_clinical_impressions=a.possible_clinical_impressions,
        possible_diagnoses=a.possible_diagnoses,
        icd10_suggestions=[
            c.ApiIcd10Suggestion(phrase=i.phrase, code=i.code, reason=i.reason, confidence=i.confidence)
            for i in a.icd10_suggestions
        ],
        body_regions=[c.ApiBodyRegion(phrase=b.phrase, region=b.region) for b in a.body_regions],
        cpt_suggestions=[
            c.ApiCptSuggestion(
                code=s.code,
                label=s.label,
                display_name=s.display_name,
                descriptor=s.descriptor,
                matched_phrases=s.matched_phrases,
                documentation_requirements=s.documentation_requirements,
                billing_caveats=s.billing_caveats,
                reason=s.reason,
                confidence=s.confidence,
            )
            for s in a.cpt_suggestions
        ],
        ncci_conflicts=[
            c.ApiNcciConflict(
                cpt_a=n.cpt_a,
                cpt_b=n.cpt_b,
                conflict_type=n.conflict_type,
                body_region_sensitive=n.body_region_sensitive,
                modifier_59_possible=n.modifier_59_possible,
                explanation=n.explanation,
                severity=n.severity,
            )
            for n in a.ncci_conflicts
        ],
        symptoms=a.symptoms,
        soap_update=c.ApiSoapUpdate(
            subjective=a.soap_update.subjective,
            objective=a.soap_update.objective,
            assessment=a.soap_update.assessment,
            plan=a.soap_update.plan,
        ),
        billing_hints=a.billing_hints,
        confidence=a.confidence,
        disclaimer=a.disclaimer,
    )
    if state is None:
        return base

    live: list[c.ApiLiveSuggestion] = []
    for suggestion in state.suggestions:
        if suggestion.status == "dismissed":
            continue
        live.append(
            c.ApiLiveSuggestion(
                id=suggestion.suggestion_id,
                type="billing",
                title=suggestion.title,
                description=suggestion.message,
                action_label="Apply",
                status="applied" if suggestion.status == "applied" else "pending",
            )
        )
    for insight in state.insights:
        live.append(
            c.ApiLiveSuggestion(
                id=insight.insight_id,
                type=insight.type if insight.type in {"protocol", "detected", "detected_icd", "billing"} else "detected",
                title=insight.label,
                description=insight.description,
                action_label="Accept" if insight.type == "detected_icd" else "Review",
                status={  # type: ignore[arg-type]
                    "approved": "applied",
                    "ignored": "ignored",
                    "pending": "pending",
                }[insight.status],
            )
        )

    timer_suggestion: c.ApiCptTimerSuggestion | None = None
    for cpt in a.cpt_suggestions:
        if cpt.confidence in ("high", "medium"):
            timer_suggestion = c.ApiCptTimerSuggestion(
                should_start=True,
                code=cpt.code,
                display_name=cpt.display_name,
                reason=cpt.reason or "Procedure detected from transcript.",
                confidence=cpt.confidence,
            )
            break

    return base.model_copy(update={
        "live_suggestions": live,
        "cpt_timer_suggestion": timer_suggestion,
    })


# ---------------------------------------------------------------------------
# Insights (protocol / detected / billing cards)
# ---------------------------------------------------------------------------
def _insight_id(kind: str, key: str) -> str:
    digest = hashlib.sha1(f"{kind}:{key}".encode()).hexdigest()[:12]
    return f"{kind}-{digest}"


def derive_insights(analysis: ClinicalAnalysis, *, include_cpt_cards: bool = True) -> list[ProtocolInsight]:
    """Turn a clinical analysis into stable, dedupable insight cards.

    IDs are content-derived so repeated transcript chunks reconcile to the same
    card (and a clinician's approve/ignore decision is preserved across refreshes)."""
    insights: list[ProtocolInsight] = []

    # Protocol-level question insights from diagnoses (first 2)
    for diagnosis in analysis.possible_diagnoses[:2]:
        insights.append(
            ProtocolInsight(
                insight_id=_insight_id("protocol", diagnosis),
                type="protocol",
                label="Protocol Ask",
                question=f"Does the patient report symptoms consistent with {diagnosis}?",
                description="Confirm clinical findings and document support for this impression.",
            )
        )

    # Groq/LLM patient questions (Path B only in Phase 3)
    for hint in analysis.billing_hints:
        if hint.startswith("💡 Suggestion:"):
            question_text = hint.replace("💡 Suggestion:", "").strip()
            insights.append(
                ProtocolInsight(
                    insight_id=_insight_id("protocol", question_text),
                    type="protocol",
                    label="Protocol Ask",
                    question=question_text,
                    description="AI-generated question to ask the patient during the session.",
                )
            )

    # CPT code detection cards (from rules/JSON when include_cpt_cards=True; Groq path skips these)
    if include_cpt_cards:
        for cpt in analysis.cpt_suggestions:
            display = cpt.display_name or cpt.label or cpt.code
            insights.append(
                ProtocolInsight(
                    insight_id=_insight_id("detected", cpt.code),
                    type="detected",
                    label="Detected",
                    question=f"Bill {display} ({cpt.code})?",
                    description=cpt.reason or cpt.descriptor or f"Matched: {', '.join(cpt.matched_phrases)}",
                )
            )

    # NCCI conflict cards
    for conflict in analysis.ncci_conflicts:
        key = "-".join(sorted((conflict.cpt_a, conflict.cpt_b)))
        insights.append(
            ProtocolInsight(
                insight_id=_insight_id("billing", key),
                type="billing",
                label=f"NCCI: {conflict.cpt_a} + {conflict.cpt_b}",
                question="Apply Modifier 59?" if conflict.modifier_59_possible else "Review billing conflict",
                description=conflict.explanation,
            )
        )

    return insights


def merge_insights(
    existing: list[ProtocolInsight], fresh: list[ProtocolInsight]
) -> list[ProtocolInsight]:
    """Union by id, preserving any prior approve/ignore status."""
    by_id = {i.insight_id: i for i in existing}
    for item in fresh:
        if item.insight_id not in by_id:
            by_id[item.insight_id] = item
    return list(by_id.values())


def insight_to_contract(i: ProtocolInsight) -> c.ApiInsight:
    return c.ApiInsight(
        id=i.insight_id,
        type=i.type,
        label=i.label,
        question=i.question,
        description=i.description,
        status=i.status,
        validation_status=i.validation_status,
        code=i.code,
    )


def icd10_am_insight_to_contract(i: ProtocolInsight) -> c.ApiDetectedIcd10Am:
    return c.ApiDetectedIcd10Am(
        id=i.insight_id,
        code=i.code or "",
        label=i.label,
        question=i.question,
        description=i.description,
        status=i.status,
        validation_status=i.validation_status,
    )


def suggestion_to_contract(s: Suggestion) -> c.ApiSuggestion:
    return c.ApiSuggestion(
        id=s.suggestion_id,
        title=s.title,
        text=s.message,
        applied=s.status == "applied",
    )


def assistant_suggestion_to_contract(s: AssistantSuggestion) -> c.ApiAssistantSuggestion:
    return c.ApiAssistantSuggestion(
        id=s.suggestion_id,
        trigger_id=s.trigger_id,
        kind=s.kind,
        title=s.title,
        body=s.body,
        confidence=s.confidence,
        status=s.status,
        disclaimer=s.disclaimer,
        created_at=s.created_at.isoformat(),
    )


def documentation_review_to_contract(report: DocumentationReviewReport) -> c.ApiDocumentationReview:
    return c.ApiDocumentationReview(
        session_id=report.session_id,
        items=[
            c.ApiDocumentationReviewItem(
                id=item.item_id,
                category=item.category,
                severity=item.severity,
                title=item.title,
                detail=item.detail,
                resolved=item.resolved,
            )
            for item in report.items
        ],
        open_count=report.open_count,
        generated_at=report.generated_at.isoformat(),
    )


def documentation_review_summary(
    report: DocumentationReviewReport | None,
) -> c.DocumentationReviewSummary | None:
    if report is None:
        return None
    return c.DocumentationReviewSummary(
        open_count=report.open_count,
        item_count=len(report.items),
    )


# ---------------------------------------------------------------------------
# SOAP <-> DTO
# ---------------------------------------------------------------------------
def soap_to_dto(note: SoapNote) -> c.SoapDataDTO:
    return c.SoapDataDTO(
        subjective=c.SoapSubjectiveDTO(
            chief_complaint=note.subjective.chief_complaint,
            pain_scale=note.subjective.pain_scale,
            duration=note.subjective.duration,
        ),
        objective=c.SoapObjectiveDTO(
            observation_notes=note.objective.observation_notes,
            range_of_motion=note.objective.range_of_motion,
            affect=note.objective.affect,
            vital_signs=note.objective.vital_signs,
        ),
        assessment=c.SoapAssessmentDTO(
            diagnosis_summary=note.assessment.diagnosis_summary,
            primary_diagnosis_code=note.assessment.primary_diagnosis_code,
            severity=note.assessment.severity,
        ),
        plan=c.SoapPlanDTO(follow_up_plan=note.plan.follow_up_plan),
        billing_documentation=c.SoapBillingDocumentationDTO(
            intervention_blocks=note.billing_documentation.intervention_blocks,
            cpt_summary=note.billing_documentation.cpt_summary,
            ncci_alerts=note.billing_documentation.ncci_alerts,
            compliance_gaps=note.billing_documentation.compliance_gaps,
            total_session_minutes=note.billing_documentation.total_session_minutes,
        ),
    )


def dto_to_soap(dto: c.SoapDataDTO, *, generated: bool) -> SoapNote:
    from medexa.schemas import (
        SoapAssessment,
        SoapBillingDocumentation,
        SoapObjective,
        SoapPlan,
        SoapSubjective,
    )

    return SoapNote(
        subjective=SoapSubjective(
            chief_complaint=dto.subjective.chief_complaint,
            pain_scale=dto.subjective.pain_scale,
            duration=dto.subjective.duration,
        ),
        objective=SoapObjective(
            observation_notes=dto.objective.observation_notes,
            range_of_motion=dto.objective.range_of_motion,
            affect=dto.objective.affect,
            vital_signs=dto.objective.vital_signs,
        ),
        assessment=SoapAssessment(
            diagnosis_summary=dto.assessment.diagnosis_summary,
            primary_diagnosis_code=dto.assessment.primary_diagnosis_code,
            severity=dto.assessment.severity,
        ),
        plan=SoapPlan(follow_up_plan=dto.plan.follow_up_plan),
        billing_documentation=SoapBillingDocumentation(
            intervention_blocks=dto.billing_documentation.intervention_blocks,
            cpt_summary=dto.billing_documentation.cpt_summary,
            ncci_alerts=dto.billing_documentation.ncci_alerts,
            compliance_gaps=dto.billing_documentation.compliance_gaps,
            total_session_minutes=dto.billing_documentation.total_session_minutes,
        ),
        generated=generated,
    )


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
def _modifier_for(state: SessionState, code: str) -> str:
    """Return "59" when an NCCI conflict touching this code allows Modifier 59."""
    for alert in state.alerts:
        if code in alert.cpt_codes and "Modifier 59" in alert.message:
            return "59"
    if state.latest_analysis:
        for conflict in state.latest_analysis.ncci_conflicts:
            if code in (conflict.cpt_a, conflict.cpt_b) and conflict.modifier_59_possible:
                return "59"
    return ""


def _warning_for(state: SessionState, code: str) -> str:
    for alert in state.alerts:
        if code in alert.cpt_codes:
            return alert.message
    return ""


def billing_to_contract(state: SessionState, summary: BillingSummary) -> c.ApiBilling:
    review = {r.cpt_code: r for r in state.billing_review}
    emr = summary.eight_minute_rule

    cpt_codes: list[c.ApiBillingCpt] = []
    for item in summary.line_items:
        override = review.get(item.cpt_code)
        cpt_codes.append(
            c.ApiBillingCpt(
                id=item.cpt_code,
                code=item.cpt_code,
                title=item.display_name,
                units=str(item.units),
                duration=format_mmss(item.total_seconds),
                warning=(override.warning if override and override.warning else _warning_for(state, item.cpt_code)),
                note=override.note if override else None,
                status=override.status if override else "pending",
            )
        )

    # Clinician-added manual codes not detected by the engine.
    for r in state.billing_review:
        if r.manual and not any(ci.code == r.cpt_code for ci in cpt_codes):
            cpt_codes.append(
                c.ApiBillingCpt(
                    id=r.cpt_code,
                    code=r.cpt_code,
                    title=r.title or r.cpt_code,
                    units=r.units or "1",
                    duration=r.duration or "00:00",
                    warning=r.warning or "",
                    note=r.note,
                    status=r.status,
                )
            )

    seconds_to_next = emr.seconds_to_next_unit if emr else 0
    threshold = (
        f"{format_mmss(seconds_to_next)} to next unit (CMS 8-Minute Rule)"
        if emr
        else "No timed units accrued yet"
    )
    return c.ApiBilling(
        session_time=format_mmss(sum(li.total_seconds for li in summary.line_items)),
        units=str(summary.total_units),
        threshold=threshold,
        cpt_codes=cpt_codes,
        snf_functional_logic=c.ApiSnfFunctionalLogic(
            section="GG0130 Self-Care / GG0170 Mobility",
            level="Pending clinician review",
        ),
    )


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
def claim_to_contract(state: SessionState, summary: BillingSummary) -> c.ApiClaim:
    claim = state.claim
    d = state.patient_display

    cpt_items: list[c.ApiClaimCpt] = [
        c.ApiClaimCpt(
            id=item.cpt_code,
            code=item.cpt_code,
            description=item.display_name,
            units=str(item.units),
            duration=format_mmss(item.total_seconds),
            modifier=_modifier_for(state, item.cpt_code),
        )
        for item in summary.line_items
        if item.units > 0
    ]
    for extra in claim.extra_line_items:
        cpt_items.append(
            c.ApiClaimCpt(
                id=extra.line_id,
                code=extra.code,
                description=extra.description,
                units=extra.units,
                duration=extra.duration,
                modifier=extra.modifier,
            )
        )

    # Diagnoses: explicit claim diagnoses win; otherwise derive from analysis.
    diagnosis_codes: list[c.ApiClaimDiagnosis] = []
    if claim.diagnoses:
        diagnosis_codes = [
            c.ApiClaimDiagnosis(id=dx.diagnosis_id, code=dx.code, description=dx.description, type=dx.type)
            for dx in claim.diagnoses
        ]
    elif state.latest_analysis:
        for idx, icd in enumerate(state.latest_analysis.icd10_suggestions[:5]):
            diagnosis_codes.append(
                c.ApiClaimDiagnosis(
                    id=icd.code,
                    code=icd.code,
                    description=icd.phrase.title(),
                    type="Primary" if idx == 0 else "Secondary",
                )
            )

    return c.ApiClaim(
        patient_meta=c.ApiPatientMeta(
            patient=state.patient_name or "",
            mrn=state.mrn or "",
            provider=claim.provider or (state.therapist_id or ""),
            session=claim.session_label or (state.session_type or "") or d.date_time,
            payor=claim.payor or d.payor_source,
        ),
        cpt_items=cpt_items,
        diagnosis_codes=diagnosis_codes,
        claim_status=claim.status,
    )
