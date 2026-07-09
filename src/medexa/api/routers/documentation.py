from __future__ import annotations

from fastapi import APIRouter, Depends

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import require_state

router = APIRouter(tags=["documentation"])


# --- SOAP notes ------------------------------------------------------------
@router.get("/soap-notes/{session_id}", response_model=c.SoapDataDTO)
async def get_soap_notes(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.SoapDataDTO:
    return m.soap_to_dto(require_state(session_id, container).soap)


@router.put("/soap-notes/{session_id}", response_model=c.SoapDataDTO)
async def update_soap_notes(
    session_id: str,
    body: c.SoapDataDTO,
    container: ServiceContainer = Depends(get_container),
) -> c.SoapDataDTO:
    state = require_state(session_id, container)
    state.soap = m.dto_to_soap(body, generated=state.soap.generated)
    container.session_repo.save(state)
    return m.soap_to_dto(state.soap)


@router.post("/soap-notes/{session_id}/generate", response_model=c.SoapDataDTO)
async def generate_soap_notes(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.SoapDataDTO:
    state = require_state(session_id, container)
    state.soap = container.soap_generator.generate(state)
    container.session_repo.save(state)
    return m.soap_to_dto(state.soap)


# --- Patient summary -------------------------------------------------------
@router.get("/patient-summary/{session_id}", response_model=c.PatientSummaryDTO)
async def get_patient_summary(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.PatientSummaryDTO:
    doc = require_state(session_id, container).patient_summary
    return c.PatientSummaryDTO(summary=doc.summary, sent=doc.sent)


@router.put("/patient-summary/{session_id}", response_model=c.PatientSummaryDTO)
async def update_patient_summary(
    session_id: str,
    body: c.UpdatePatientSummaryRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.PatientSummaryDTO:
    state = require_state(session_id, container)
    state.patient_summary.summary = body.summary
    container.session_repo.save(state)
    return c.PatientSummaryDTO(summary=state.patient_summary.summary, sent=state.patient_summary.sent)


@router.post("/patient-summary/{session_id}/generate", response_model=c.PatientSummaryDTO)
async def generate_patient_summary(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.PatientSummaryDTO:
    state = require_state(session_id, container)
    state.patient_summary.summary = container.summary_generator.generate(state)
    container.session_repo.save(state)
    return c.PatientSummaryDTO(summary=state.patient_summary.summary, sent=state.patient_summary.sent)


@router.post("/patient-summary/{session_id}/send", response_model=c.PatientSummaryDTO)
async def send_patient_summary(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.PatientSummaryDTO:
    state = require_state(session_id, container)
    if not state.patient_summary.summary:
        state.patient_summary.summary = container.summary_generator.generate(state)
    state.patient_summary.sent = True
    container.session_repo.save(state)
    return c.PatientSummaryDTO(summary=state.patient_summary.summary, sent=state.patient_summary.sent)
