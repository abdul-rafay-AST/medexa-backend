from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import billing_summary, require_state
from medexa.schemas import ClaimDiagnosis, ClaimLineItem, SessionState

router = APIRouter(prefix="/claims", tags=["claims"])


def _build_claim(state: SessionState, container: ServiceContainer) -> c.ApiClaim:
    return m.claim_to_contract(state, billing_summary(state, container))


@router.get("/{session_id}", response_model=c.ApiClaim)
async def get_claim(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiClaim:
    return _build_claim(require_state(session_id, container), container)


@router.post("/{session_id}/cpt", response_model=c.ApiClaimCpt)
async def add_claim_cpt(
    session_id: str,
    body: c.AddClaimCptRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiClaimCpt:
    state = require_state(session_id, container)
    line = ClaimLineItem(
        line_id=str(uuid.uuid4()),
        code=body.code,
        description=body.description or container.cpt_metadata_loader.get_display_name(body.code),
        units=body.units or "1",
        duration=body.duration or "00:00",
        modifier=body.modifier or "",
    )
    state.claim.extra_line_items.append(line)
    container.session_repo.save(state)
    return c.ApiClaimCpt(
        id=line.line_id,
        code=line.code,
        description=line.description,
        units=line.units,
        duration=line.duration,
        modifier=line.modifier,
    )


@router.post("/{session_id}/diagnosis", response_model=c.ApiClaimDiagnosis)
async def add_claim_diagnosis(
    session_id: str,
    body: c.AddClaimDiagnosisRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiClaimDiagnosis:
    state = require_state(session_id, container)
    dx = ClaimDiagnosis(
        diagnosis_id=str(uuid.uuid4()),
        code=body.code,
        description=body.description or body.code,
        type=body.type,
    )
    state.claim.diagnoses.append(dx)
    container.session_repo.save(state)
    return c.ApiClaimDiagnosis(id=dx.diagnosis_id, code=dx.code, description=dx.description, type=dx.type)


@router.put("/{session_id}/session-data", response_model=c.ApiClaim)
async def update_claim_session_data(
    session_id: str,
    body: c.ApiPatientMeta,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiClaim:
    state = require_state(session_id, container)
    if body.patient:
        state.patient_name = body.patient
    if body.mrn:
        state.mrn = body.mrn
    state.claim.provider = body.provider or state.claim.provider
    state.claim.payor = body.payor or state.claim.payor
    state.claim.session_label = body.session or state.claim.session_label
    container.session_repo.save(state)
    return _build_claim(state, container)


def _set_claim_status(session_id: str, status: str, container: ServiceContainer) -> c.ApiClaim:
    state = require_state(session_id, container)
    state.claim.status = status  # type: ignore[assignment]
    container.session_repo.save(state)
    return _build_claim(state, container)


@router.post("/{session_id}/save-draft", response_model=c.ApiClaim)
async def save_claim_draft(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiClaim:
    return _set_claim_status(session_id, "draft", container)


@router.post("/{session_id}/verify", response_model=c.ApiClaim)
async def verify_claim(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiClaim:
    return _set_claim_status(session_id, "verified", container)


@router.post("/{session_id}/submit", response_model=c.ApiClaim)
async def submit_claim(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiClaim:
    return _set_claim_status(session_id, "submitted", container)
