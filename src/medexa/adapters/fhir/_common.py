from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime
from typing import Any

from medexa.schemas import BillingSummary, SessionState


def load_fhir_profile(bundle, relative_path: str) -> dict[str, Any]:
    path = bundle.asset_path(relative_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle_template(bundle, relative_path: str) -> dict[str, Any]:
    """Load one of the compliant NPHIES bundle templates (deep copy per call)."""
    path = bundle.asset_path(relative_path)
    if not path.exists():
        raise FileNotFoundError(f"NPHIES bundle template not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def find_resource(template: dict[str, Any], resource_type: str) -> dict[str, Any]:
    """Locate the first resource of a given type inside a Bundle template's entries."""
    for entry in template.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == resource_type:
            return resource
    raise ValueError(f"Resource type {resource_type!r} not found in template")


def find_organization(template: dict[str, Any], profile_suffix: str) -> dict[str, Any] | None:
    for entry in template.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") != "Organization":
            continue
        profile_url = resource.get("meta", {}).get("profile", [""])[0]
        if profile_url.endswith(profile_suffix):
            return resource
    return None


def find_extension(resource: dict[str, Any], url_suffix: str) -> dict[str, Any] | None:
    for ext in resource.get("extension", []) or []:
        if str(ext.get("url", "")).endswith(url_suffix):
            return ext
    return None


def _organization_role(resource: dict[str, Any]) -> str:
    profile_url = resource.get("meta", {}).get("profile", [""])[0]
    if "provider-organization" in profile_url:
        return "ProviderOrganization"
    if "insurer-organization" in profile_url:
        return "InsurerOrganization"
    if "policyholder-organization" in profile_url:
        return "PolicyholderOrganization"
    return f"Organization:{resource.get('id') or uuid.uuid4()}"


def assign_fresh_resource_ids(template: dict[str, Any]) -> dict[str, str]:
    """Assign a unique UUID to every Bundle entry and return role → id.

    Organizations are keyed by NPHIES profile role so provider and insurer
    never collide (a previous bug shared one Organization id across both).
    """
    roles: dict[str, str] = {}
    for entry in template.get("entry", []):
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")
        if not resource_type:
            continue
        role = (
            _organization_role(resource)
            if resource_type == "Organization"
            else resource_type
        )
        new_id = str(uuid.uuid4())
        roles[role] = new_id
        resource["id"] = new_id
        entry["fullUrl"] = f"urn:uuid:{new_id}"
    return roles


def wire_bundle_references(template: dict[str, Any], roles: dict[str, str]) -> None:
    """Fill internal Claim/Coverage/Encounter references after fresh ids are assigned."""
    claim = find_resource(template, "Claim")
    message_header = find_resource(template, "MessageHeader")

    if "Claim" in roles:
        message_header["focus"] = [{"reference": f"urn:uuid:{roles['Claim']}"}]

    if "Patient" in roles:
        claim["patient"] = {"reference": f"Patient/{roles['Patient']}"}
    if "ProviderOrganization" in roles:
        claim["provider"] = {"reference": f"Organization/{roles['ProviderOrganization']}"}
    if "InsurerOrganization" in roles:
        claim["insurer"] = {"reference": f"Organization/{roles['InsurerOrganization']}"}

    encounter_ext = find_extension(claim, "extension-encounter")
    if encounter_ext is not None and "Encounter" in roles:
        encounter_ext["valueReference"] = {"reference": f"Encounter/{roles['Encounter']}"}

    if claim.get("careTeam") and "Practitioner" in roles:
        claim["careTeam"][0]["provider"] = {
            "reference": f"Practitioner/{roles['Practitioner']}"
        }

    if claim.get("insurance") and "Coverage" in roles:
        claim["insurance"][0]["coverage"] = {
            "reference": f"Coverage/{roles['Coverage']}"
        }

    coverage = find_resource(template, "Coverage")
    if "Patient" in roles:
        coverage["subscriber"] = {"reference": f"Patient/{roles['Patient']}"}
        coverage["beneficiary"] = {"reference": f"Patient/{roles['Patient']}"}
    if "InsurerOrganization" in roles:
        coverage["payor"] = [{"reference": f"Organization/{roles['InsurerOrganization']}"}]

    encounter = find_resource(template, "Encounter")
    if "Patient" in roles:
        encounter["subject"] = {"reference": f"Patient/{roles['Patient']}"}
    if "ProviderOrganization" in roles:
        encounter["serviceProvider"] = {
            "reference": f"Organization/{roles['ProviderOrganization']}"
        }


# Backwards-compatible aliases used by existing builders.
def new_resource_ids(template: dict[str, Any]) -> dict[str, str]:
    return assign_fresh_resource_ids(template)


def rewrite_references(template: dict[str, Any], ids: dict[str, str]) -> None:
    """Assign ids (if not already) and wire NPHIES internal references."""
    roles = ids if ids else assign_fresh_resource_ids(template)
    # Ensure entry fullUrls/ids match the role map when callers pre-built ids.
    for entry in template.get("entry", []):
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType")
        if not resource_type:
            continue
        role = (
            _organization_role(resource)
            if resource_type == "Organization"
            else resource_type
        )
        if role in roles:
            resource["id"] = roles[role]
            entry["fullUrl"] = f"urn:uuid:{roles[role]}"
    wire_bundle_references(template, roles)


def deep_copy_template(template: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(template)


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
                            "http://nphies.sa/terminology/CodeSystem/services",
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
        "identifier": [
            {
                "system": f"http://medexa.internal/{org_type}-id",
                "value": identifier_value or organization_id,
            }
        ],
        "name": org_type.title(),
    }
