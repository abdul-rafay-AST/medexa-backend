from __future__ import annotations

from datetime import timedelta

from medexa.adapters.fhir.sa.claim_bundle_builder import NphiesClaimBundleBuilder
from medexa.adapters.fhir.sa.priorauth_bundle_builder import NphiesPriorAuthBundleBuilder
from medexa.adapters.storage.in_memory_storage import InMemoryObjectStorage
from medexa.api.dependencies import ServiceContainer
from medexa.application.fhir_export_service import FhirExportService
from medexa.regions.factory import build_priorauth_fhir_exporter
from medexa.schemas import BillingLineItem, BillingSummary, SessionState, TimerSegment
from medexa.utils.time import now_utc

SERVICES_CS = "http://nphies.sa/terminology/CodeSystem/services"
REQUIRED_SUPPORTING_INFO = {
    "vital-sign-systolic",
    "vital-sign-diastolic",
    "vital-sign-height",
    "vital-sign-weight",
    "pulse",
    "temperature",
    "respiratory-rate",
    "oxygen-saturation",
    "chief-complaint",
    "patient-history",
    "history-of-present-illness",
    "physical-examination",
    "treatment-plan",
    "investigation-result",
}


def _sample_state_and_summary(session_id: str = "sa-fhir") -> tuple[SessionState, BillingSummary]:
    now = now_utc()
    state = SessionState(
        session_id=session_id,
        billing_region="SA",
        payer_id="payer-1",
        member_id="member-1",
        therapist_id="therapist-1",
        pre_auth_reference="PA-123",
        patient_name="Test Patient",
        timer_segments=[
            TimerSegment(
                segment_id="seg-1",
                cpt_code="95550-03-00",
                body_region="knee_right",
                start_time=now - timedelta(minutes=30),
                stop_time=now,
                accumulated_seconds=1800,
            )
        ],
    )
    summary = BillingSummary(
        session_id=session_id,
        total_minutes=30,
        total_units=1,
        line_items=[
            BillingLineItem(
                cpt_code="95550-03-00",
                display_name="Allied health intervention, physiotherapy",
                timed=False,
                total_seconds=1800,
                units=1,
            )
        ],
        generated_at=now,
    )
    return state, summary


def _claim_resource(bundle: dict) -> dict:
    return next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Claim")


def _encounter_resource(bundle: dict) -> dict:
    return next(
        e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Encounter"
    )


def test_nphies_claim_bundle_is_structurally_compliant() -> None:
    container = ServiceContainer()
    region = container.region_registry.resolve("SA")
    builder = NphiesClaimBundleBuilder(region)
    state, summary = _sample_state_and_summary("sa-claim")

    payload = builder.build_claim_bundle(state, summary)
    claim = _claim_resource(payload)
    encounter = _encounter_resource(payload)
    item = claim["item"][0]

    assert payload["resourceType"] == "Bundle"
    assert payload["type"] == "message"
    resource_types = {entry["resource"]["resourceType"] for entry in payload["entry"]}
    assert resource_types == {
        "MessageHeader",
        "Claim",
        "Patient",
        "Coverage",
        "Organization",
        "Practitioner",
        "Encounter",
    }

    assert claim["use"] == "claim"
    assert claim["subType"]["coding"][0]["code"] == "op"
    assert claim["meta"]["profile"][0].endswith("professional-claim|1.0.0")

    claim_exts = {ext["url"].split("/")[-1] for ext in claim["extension"]}
    assert "extension-episode" in claim_exts
    assert "extension-encounter" in claim_exts

    si_codes = {row["category"]["coding"][0]["code"] for row in claim["supportingInfo"]}
    assert REQUIRED_SUPPORTING_INFO <= si_codes

    item_exts = {ext["url"].split("/")[-1]: ext for ext in item["extension"]}
    assert "extension-maternity" in item_exts
    assert item_exts["extension-maternity"]["valueBoolean"] is False
    assert "extension-patientInvoice" in item_exts
    assert item["productOrService"]["coding"][0]["system"] == SERVICES_CS

    orgs = [e["resource"] for e in payload["entry"] if e["resource"]["resourceType"] == "Organization"]
    assert len({org["id"] for org in orgs}) == 2

    assert encounter["meta"]["profile"][0].endswith("encounter-claim-AMB|1.0.0")
    assert encounter["class"]["code"] == "AMB"
    assert encounter["status"] == "finished"
    assert claim["patient"]["reference"].startswith("Patient/")
    assert claim["provider"]["reference"].startswith("Organization/")
    assert claim["insurer"]["reference"].startswith("Organization/")


def test_nphies_priorauth_bundle_is_structurally_compliant() -> None:
    container = ServiceContainer()
    region = container.region_registry.resolve("SA")
    builder = NphiesPriorAuthBundleBuilder(region)
    state, summary = _sample_state_and_summary("sa-priorauth")

    payload = builder.build_priorauth_bundle(state, summary)
    claim = _claim_resource(payload)
    encounter = _encounter_resource(payload)
    item = claim["item"][0]

    assert payload["type"] == "message"
    assert claim["use"] == "preauthorization"
    assert claim["subType"]["coding"][0]["code"] == "op"
    assert claim["meta"]["profile"][0].endswith("professional-priorauth|1.0.0")

    claim_exts = {ext["url"].split("/")[-1] for ext in claim["extension"]}
    assert "extension-eligibility-response" in claim_exts
    assert "extension-encounter" in claim_exts
    assert "extension-episode" not in claim_exts

    si_codes = {row["category"]["coding"][0]["code"] for row in claim["supportingInfo"]}
    assert REQUIRED_SUPPORTING_INFO <= si_codes

    item_exts = {ext["url"].split("/")[-1]: ext for ext in item["extension"]}
    assert item_exts["extension-package"]["valueBoolean"] is False
    assert item_exts["extension-maternity"]["valueBoolean"] is False
    assert "extension-patientInvoice" not in item_exts
    assert item["productOrService"]["coding"][0]["system"] == SERVICES_CS

    assert encounter["meta"]["profile"][0].endswith("encounter-auth-AMB|1.0.0")
    assert encounter["class"]["code"] == "AMB"
    assert encounter["status"] == "in-progress"
    assert "end" not in encounter.get("period", {})


def test_factory_wires_priorauth_exporter() -> None:
    container = ServiceContainer()
    region = container.region_registry.resolve("SA")
    exporter = build_priorauth_fhir_exporter(region)
    assert isinstance(exporter, NphiesPriorAuthBundleBuilder)


def test_fhir_export_persists_claim_and_priorauth() -> None:
    container = ServiceContainer()
    region = container.region_registry.resolve("SA")
    storage = InMemoryObjectStorage()
    state, summary = _sample_state_and_summary("sa-export")

    claim_artifact = FhirExportService().export_session(
        state, summary, NphiesClaimBundleBuilder(region), storage
    )
    priorauth_artifact = FhirExportService().export_priorauth(
        state, summary, NphiesPriorAuthBundleBuilder(region), storage
    )

    assert claim_artifact.storage_uri is not None
    assert priorauth_artifact.storage_uri is not None
    assert storage.exists(claim_artifact.storage_key or "")
    assert storage.exists(priorauth_artifact.storage_key or "")
    assert priorauth_artifact.profile_id == "nphies-professional-priorauth"
