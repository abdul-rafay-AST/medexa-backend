from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime
from typing import Any

from medexa.schemas import BillingSummary, SessionState

MEDEXA_ENDPOINT = "https://medexa.internal/nphies"
MEMBER_ID_SYSTEM = "https://medexa.internal/identifiers/member-id"
SERVICES_CODE_SYSTEM = "http://nphies.sa/terminology/CodeSystem/services"
REHAB_PRACTICE_CODE = "16.00"
REHAB_PRACTICE_DISPLAY = "Physical Medicine & Rehabilitation Specialty"


def load_fhir_profile(bundle, relative_path: str) -> dict[str, Any]:
    path = bundle.asset_path(relative_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle_template(bundle, relative_path: str) -> dict[str, Any]:
    """Load one of the compliant NPHIES bundle templates."""
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
    never collide.
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


def _focus_resource_type(template: dict[str, Any]) -> str | None:
    for resource_type in ("Claim", "CoverageEligibilityRequest"):
        try:
            find_resource(template, resource_type)
            return resource_type
        except ValueError:
            continue
    return None


def wire_bundle_references(template: dict[str, Any], roles: dict[str, str]) -> None:
    """Fill internal references for claim, prior-auth, or eligibility bundles."""
    message_header = find_resource(template, "MessageHeader")
    focus_type = _focus_resource_type(template)

    if focus_type and focus_type in roles:
        message_header["focus"] = [{"reference": f"urn:uuid:{roles[focus_type]}"}]

    focus = find_resource(template, focus_type) if focus_type else None
    if focus is not None:
        if "Patient" in roles:
            focus["patient"] = {"reference": f"Patient/{roles['Patient']}"}
        if "ProviderOrganization" in roles:
            focus["provider"] = {
                "reference": f"Organization/{roles['ProviderOrganization']}"
            }
        if "InsurerOrganization" in roles:
            focus["insurer"] = {
                "reference": f"Organization/{roles['InsurerOrganization']}"
            }

        encounter_ext = find_extension(focus, "extension-encounter")
        if encounter_ext is not None and "Encounter" in roles:
            encounter_ext["valueReference"] = {
                "reference": f"Encounter/{roles['Encounter']}"
            }

        if focus.get("careTeam") and "Practitioner" in roles:
            focus["careTeam"][0]["provider"] = {
                "reference": f"Practitioner/{roles['Practitioner']}"
            }

        if focus.get("insurance") and "Coverage" in roles:
            focus["insurance"][0]["coverage"] = {
                "reference": f"Coverage/{roles['Coverage']}"
            }

    try:
        coverage = find_resource(template, "Coverage")
    except ValueError:
        coverage = None
    if coverage is not None:
        if "Patient" in roles:
            coverage["subscriber"] = {"reference": f"Patient/{roles['Patient']}"}
            coverage["beneficiary"] = {"reference": f"Patient/{roles['Patient']}"}
        if "InsurerOrganization" in roles:
            coverage["payor"] = [
                {"reference": f"Organization/{roles['InsurerOrganization']}"}
            ]

    try:
        encounter = find_resource(template, "Encounter")
    except ValueError:
        encounter = None
    if encounter is not None:
        if "Patient" in roles:
            encounter["subject"] = {"reference": f"Patient/{roles['Patient']}"}
        if "ProviderOrganization" in roles:
            encounter["serviceProvider"] = {
                "reference": f"Organization/{roles['ProviderOrganization']}"
            }


def new_resource_ids(template: dict[str, Any]) -> dict[str, str]:
    return assign_fresh_resource_ids(template)


def rewrite_references(template: dict[str, Any], ids: dict[str, str]) -> None:
    """Assign ids (if not already) and wire NPHIES internal references."""
    roles = ids if ids else assign_fresh_resource_ids(template)
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


def fhir_date(value: datetime) -> str:
    return value.date().isoformat()


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


def stamp_bundle_envelope(template: dict[str, Any], when: datetime) -> None:
    template["id"] = str(uuid.uuid4())
    template["timestamp"] = fhir_instant(when)


def fill_message_header_routing(template: dict[str, Any], state: SessionState) -> None:
    """Fill MessageHeader payer/provider licenses from session routing fields.

    These remain empty when session has no payer/therapist yet — NPHIES will
    reject blank licenses on live submit.
    """
    message_header = find_resource(template, "MessageHeader")
    message_header["destination"][0]["receiver"]["identifier"]["value"] = state.payer_id or ""
    message_header["sender"]["identifier"]["value"] = state.therapist_id or ""
    message_header["source"]["endpoint"] = MEDEXA_ENDPOINT


def fill_patient_demographics(template: dict[str, Any], state: SessionState) -> None:
    """Fill Patient fields available from Medexa session start.

    National ID type/gender/birthDate/maritalStatus stay empty until intake/EHR
    supplies them — those empties are intentional and would reject live.
    """
    patient = find_resource(template, "Patient")
    patient["identifier"][0]["value"] = (
        state.member_id or state.mrn or state.patient_id or ""
    )
    if not state.patient_name:
        return
    patient["name"][0]["text"] = state.patient_name
    parts = state.patient_name.split()
    patient["name"][0]["family"] = parts[-1] if parts else ""
    patient["name"][0]["given"] = parts[:-1] or [state.patient_name]


def fill_coverage_member(template: dict[str, Any], state: SessionState) -> None:
    coverage = find_resource(template, "Coverage")
    coverage["identifier"][0]["system"] = MEMBER_ID_SYSTEM
    coverage["identifier"][0]["value"] = state.member_id or ""


def fill_provider_and_insurer_orgs(template: dict[str, Any], state: SessionState) -> None:
    """Map session IDs into org identifiers.

    Live NPHIES requires official provider-license / payer-license numbers from
    clinic config + insurer directory. Session IDs are temporary placeholders.
    """
    provider_org = find_organization(template, "provider-organization|1.0.0")
    insurer_org = find_organization(template, "insurer-organization|1.0.0")
    if provider_org is not None:
        provider_org["identifier"][0]["value"] = state.therapist_id or ""
    if insurer_org is not None:
        insurer_org["identifier"][0]["value"] = state.payer_id or ""


def fill_practitioner_license(template: dict[str, Any], state: SessionState) -> None:
    try:
        practitioner = find_resource(template, "Practitioner")
    except ValueError:
        return
    practitioner["identifier"][0]["value"] = state.therapist_id or ""


def set_rehab_care_team_qualification(claim_like: dict[str, Any]) -> None:
    care_team = claim_like.get("careTeam", [{}])[0]
    coding_entry = care_team.get("qualification", {}).get("coding", [{}])[0]
    coding_entry["code"] = REHAB_PRACTICE_CODE
    coding_entry["display"] = REHAB_PRACTICE_DISPLAY


def fill_shared_party_resources(template: dict[str, Any], state: SessionState) -> None:
    """Common Patient / Coverage / Organization fill used by all SA builders."""
    fill_message_header_routing(template, state)
    fill_patient_demographics(template, state)
    fill_coverage_member(template, state)
    fill_provider_and_insurer_orgs(template, state)
    fill_practitioner_license(template, state)


def claim_items_from_summary(summary: BillingSummary) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, line in enumerate(summary.line_items, start=1):
        items.append(
            {
                "sequence": index,
                "productOrService": {
                    "coding": [
                        coding(
                            SERVICES_CODE_SYSTEM,
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
                "system": MEMBER_ID_SYSTEM,
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
