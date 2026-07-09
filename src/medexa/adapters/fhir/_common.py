from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from medexa.schemas import BillingSummary, SessionState


def load_fhir_profile(bundle, relative_path: str) -> dict[str, Any]:
    path = bundle.asset_path(relative_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def fhir_instant(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def coding(system: str, code: str, display: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"system": system, "code": code}
    if display:
        payload["display"] = display
    return payload


def reference(resource_type: str, resource_id: str) -> dict[str, str]:
    return {"reference": f"{resource_type}/{resource_id}"}


def bundle_entry(resource: dict[str, Any], *, full_url: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"resource": resource}
    if full_url:
        entry["fullUrl"] = full_url
    return entry


def claim_items_from_summary(summary: BillingSummary) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, line in enumerate(summary.line_items, start=1):
        items.append(
            {
                "sequence": index,
                "productOrService": {
                    "coding": [
                        coding(
                            "http://medexa.internal/service-category",
                            line.cpt_code,
                            line.display_name,
                        )
                    ]
                },
                "quantity": {"value": line.units},
            }
        )
    return items


def base_patient_resource(state: SessionState, patient_id: str) -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [
            {
                "system": "http://medexa.internal/member-id",
                "value": state.member_id or state.mrn or state.patient_id or patient_id,
            }
        ],
        "name": [{"text": state.patient_name or "Unknown Patient"}],
    }


def base_organization_resource(
    state: SessionState,
    organization_id: str,
    *,
    org_type: str,
) -> dict[str, Any]:
    identifier_value = state.payer_id if org_type == "insurer" else state.therapist_id or "provider"
    return {
        "resourceType": "Organization",
        "id": organization_id,
        "identifier": [{"system": f"http://medexa.internal/{org_type}-id", "value": identifier_value or organization_id}],
        "name": org_type.title(),
    }
