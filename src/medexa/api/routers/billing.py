from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import billing_summary, require_state
from medexa.schemas import BillingReviewItem, SessionState

router = APIRouter(prefix="/billing", tags=["billing"])


def _build_billing(state: SessionState, container: ServiceContainer) -> c.ApiBilling:
    return m.billing_to_contract(state, billing_summary(state, container))


def _find_cpt(billing: c.ApiBilling, cpt_id: str) -> c.ApiBillingCpt:
    row = next((x for x in billing.cpt_codes if x.id == cpt_id or x.code == cpt_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="CPT line item not found")
    return row


def _review_item(state: SessionState, code: str) -> BillingReviewItem:
    item = next((r for r in state.billing_review if r.cpt_code == code), None)
    if item is None:
        item = BillingReviewItem(cpt_code=code)
        state.billing_review.append(item)
    return item


@router.get("/{session_id}", response_model=c.ApiBilling)
async def get_billing(
    session_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiBilling:
    return _build_billing(require_state(session_id, container), container)


@router.post("/{session_id}/cpt", response_model=c.ApiBillingCpt)
async def add_billing_cpt(
    session_id: str,
    body: c.AddBillingCptRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiBillingCpt:
    state = require_state(session_id, container)
    item = _review_item(state, body.code)
    item.manual = True
    item.title = body.title or item.title or container.cpt_metadata_loader.get_display_name(body.code)
    item.units = body.units or item.units or "1"
    item.duration = body.duration or item.duration or "00:00"
    item.note = body.note or item.note
    item.warning = body.warning or item.warning
    container.session_repo.save(state)
    return _find_cpt(_build_billing(state, container), body.code)


@router.put("/{session_id}/cpt/{cpt_id}", response_model=c.ApiBillingCpt)
async def edit_billing_cpt(
    session_id: str,
    cpt_id: str,
    body: c.EditBillingCptRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiBillingCpt:
    state = require_state(session_id, container)
    item = _review_item(state, cpt_id)
    if body.title is not None:
        item.title = body.title
    if body.units is not None:
        item.units = body.units
    if body.duration is not None:
        item.duration = body.duration
    if body.note is not None:
        item.note = body.note
    if body.warning is not None:
        item.warning = body.warning
    if body.status is not None:
        item.status = body.status
    container.session_repo.save(state)
    return _find_cpt(_build_billing(state, container), cpt_id)


@router.post("/{session_id}/cpt/{cpt_id}/approve", response_model=c.ApiBillingCpt)
async def approve_billing_cpt(
    session_id: str, cpt_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiBillingCpt:
    state = require_state(session_id, container)
    _review_item(state, cpt_id).status = "approved"
    container.session_repo.save(state)
    return _find_cpt(_build_billing(state, container), cpt_id)


@router.post("/{session_id}/cpt/{cpt_id}/reject", response_model=c.ApiBillingCpt)
async def reject_billing_cpt(
    session_id: str, cpt_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiBillingCpt:
    state = require_state(session_id, container)
    _review_item(state, cpt_id).status = "rejected"
    container.session_repo.save(state)
    return _find_cpt(_build_billing(state, container), cpt_id)
