from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import (
    billing_now,
    billing_summary,
    recording_math,
    refresh_and_publish,
    require_state,
)
from medexa.logging_setup import get_logger
from medexa.domain.billing_region import normalize_billing_region
from medexa.schemas import PatientDisplay, SessionState
from medexa.utils.time import now_utc

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = get_logger("medexa.api.sessions")


def _recording_state(state: SessionState, container: ServiceContainer) -> c.ApiRecordingState:
    now = billing_now(state)
    runtime = container.runtime_for_state(state.billing_region)
    metrics = runtime.billing_engine.compute_metrics(state, now)
    summary = runtime.billing_summary_builder.build(state, now)
    math = recording_math(
        summary,
        billing_elapsed_seconds=metrics.timed_pool_seconds,
        cpt_elapsed_seconds=metrics.running_segment_seconds,
    )
    return m.recording_state(
        state,
        elapsed_seconds=math.elapsed_seconds,
        units=math.units,
        seconds_to_next_unit=math.seconds_to_next_unit,
        billing_elapsed_seconds=math.billing_elapsed_seconds,
        cpt_elapsed_seconds=math.cpt_elapsed_seconds,
    )


@router.get("", response_model=list[c.ApiSession])
async def list_sessions(
    status: str | None = None,
    container: ServiceContainer = Depends(get_container),
) -> list[c.ApiSession]:
    """Dashboard session list. ``?status=all`` includes ended/paused sessions."""
    if status in (None, "active"):
        sessions = container.session_repo.list_active()
    else:
        sessions = container.session_repo.list_all()
        if status not in ("all", None):
            sessions = [s for s in sessions if s.status == status]
    return [m.session_to_api(s) for s in sessions]


@router.get("/{session_id}", response_model=c.ApiSession)
async def get_session(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiSession:
    return m.session_to_api(require_state(session_id, container))


@router.post("/start", response_model=c.StartSessionResponse)
async def start_session(
    req: c.StartSessionRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.StartSessionResponse:
    session_id = str(uuid.uuid4())
    billing_region = normalize_billing_region(req.billing_region)
    runtime = container.runtime_for_region(billing_region)
    state = SessionState(
        session_id=session_id,
        billing_region=billing_region,
        emirate=req.emirate,
        patient_id=req.patient_id or req.id,
        patient_name=req.patient_name,
        mrn=req.mrn or req.mrn_number,
        therapist_id=req.therapist_id,
        session_type=req.session_type or req.care_type,
        payer_id=req.payer_id,
        member_id=req.member_id,
        pre_auth_reference=req.pre_auth_reference,
        status="active",
        patient_display=PatientDisplay(
            avatar=req.avatar or "",
            age_sex=req.age_sex or "",
            weight=req.weight or "",
            payor_source=req.payor_source or "",
            care_type=req.care_type or "",
            cpt=req.cpt or "",
            icd=req.icd or "",
            session_time=req.session_time or "",
            date_time=req.date_time or "",
        ),
    )
    start_result = container.session_start.bootstrap(
        state,
        runtime,
        runtime.pre_auth_exchange,
    )
    state = start_result.state
    container.session_repo.save(state)
    logger.info("session_started", extra={"extra_fields": {"session_id": session_id}})
    return c.StartSessionResponse(
        session=m.session_to_api(state),
        state=_recording_state(state, container),
    )


@router.get("/{session_id}/state", response_model=c.ApiRecordingState)
async def get_state(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiRecordingState:
    return _recording_state(require_state(session_id, container), container)


@router.post("/{session_id}/state", response_model=c.ApiRecordingState)
async def update_state(
    session_id: str,
    req: c.UpdateRecordingStateRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiRecordingState:
    """Recording control via a single state-machine endpoint (the frontend's
    Pause / Resume / Stop buttons map to ``paused`` / ``recording`` / ``stopped``)."""
    state = require_state(session_id, container)

    if req.elapsed_seconds is not None:
        state.client_elapsed_seconds = req.elapsed_seconds

    if req.status == "recording":
        state.status = "active"
        # Resume: re-arm the CPT that was active when paused, if any.
        if state.active_cpt and not any(seg.stop_time is None for seg in state.timer_segments):
            container.timer_engine.start_segment(
                state, state.active_cpt, state.active_body_region, billing_now(state)
            )
    elif req.status == "paused":
        container.timer_engine.stop_all_running(state, billing_now(state))
        state.status = "paused"
    elif req.status in ("stopped", "idle"):
        container.timer_engine.stop_all_running(state, billing_now(state))
        state.status = "ended" if req.status == "stopped" else state.status

    await refresh_and_publish(state, container)
    return _recording_state(state, container)


@router.post("/{session_id}/finalize-session", response_model=c.FinalizeSessionResponse)
async def finalize_session(
    session_id: str,
    body: c.FinalizeSessionRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.FinalizeSessionResponse:
    """End-of-session handoff: persist transcript, generate SOAP + summary, optional FHIR export."""
    state = require_state(session_id, container)
    now = now_utc()
    runtime = container.runtime_for_state(state.billing_region)

    result = container.finalize_orchestrator.finalize(
        state,
        runtime,
        body,
        now=now,
        object_storage=container.export_object_storage(),
    )
    container.session_repo.save(result.state)

    summary = result.billing_summary
    active_code = result.state.active_cpt or (summary.line_items[0].cpt_code if summary.line_items else None)
    active_seconds = next(
        (item.total_seconds for item in summary.line_items if item.cpt_code == active_code),
        0,
    )

    fhir_summary = None
    if result.fhir_export is not None:
        artifact = result.fhir_export
        fhir_summary = c.FhirExportSummary(
            profile_id=artifact.profile_id,
            bundle_id=artifact.bundle_id,
            storage_uri=artifact.storage_uri,
            storage_key=artifact.storage_key,
            byte_size=artifact.byte_size,
            checksum_sha256=artifact.checksum_sha256,
            exported_at=artifact.exported_at.isoformat(),
        )

    reconciliation_summary = None
    if result.pre_auth_reconciliation is not None:
        report = result.pre_auth_reconciliation
        reconciliation_summary = c.PreAuthReconciliationSummary(
            reconciled=report.reconciled,
            snapshot_status=report.snapshot_status,
            pre_auth_reference=report.pre_auth_reference,
            open_violation_count=len(report.open_violations),
        )

    return c.FinalizeSessionResponse(
        session_id=session_id,
        soap_note=m.soap_to_dto(result.state.soap),
        summary=result.state.patient_summary.summary,
        documentation_source=result.documentation_source,
        billing_summary={
            "total_seconds": sum(item.total_seconds for item in summary.line_items),
            "cpt_code": active_code,
            "cpt_seconds": active_seconds,
            "units": summary.total_units,
        },
        redirect_url=f"/soap-notes?sessionId={session_id}",
        fhir_export=fhir_summary,
        pre_auth_reconciliation=reconciliation_summary,
        documentation_review=m.documentation_review_summary(result.documentation_review),
    )


@router.get("/{session_id}/documentation-review", response_model=c.ApiDocumentationReview)
async def get_documentation_review(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiDocumentationReview:
    """Path C documentation checklist — unresolved NCCI, units, pre-auth, assistant hints."""
    state = require_state(session_id, container)
    if state.documentation_review is None:
        runtime = container.runtime_for_state(state.billing_region)
        billing_summary = runtime.billing_summary_builder.build(state, now_utc())
        report = container.finalize_orchestrator.review_builder.build(state, billing_summary)
        return m.documentation_review_to_contract(report)
    return m.documentation_review_to_contract(state.documentation_review)
