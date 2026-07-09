from __future__ import annotations

from datetime import timedelta

from medexa.adapters.fhir.sa.claim_bundle_builder import NphiesClaimBundleBuilder
from medexa.adapters.storage.in_memory_storage import InMemoryObjectStorage
from medexa.api.dependencies import ServiceContainer
from medexa.application.fhir_export_service import FhirExportService
from medexa.schemas import BillingLineItem, BillingSummary, SessionState, TimerSegment
from medexa.utils.time import now_utc


def test_nphies_bundle_contains_claim_message_and_patient() -> None:
    container = ServiceContainer()
    bundle = container.region_registry.resolve("SA")
    builder = NphiesClaimBundleBuilder(bundle)
    now = now_utc()
    state = SessionState(
        session_id="sa-fhir",
        billing_region="SA",
        payer_id="payer-1",
        member_id="member-1",
        pre_auth_reference="PA-123",
        patient_name="Test Patient",
        timer_segments=[
            TimerSegment(
                segment_id="seg-1",
                cpt_code="therapy_session",
                body_region="knee_right",
                start_time=now - timedelta(minutes=30),
                stop_time=now,
                accumulated_seconds=1800,
            )
        ],
    )
    summary = BillingSummary(
        session_id="sa-fhir",
        total_minutes=30,
        total_units=1,
        line_items=[
            BillingLineItem(
                cpt_code="therapy_session",
                display_name="Therapy Session",
                timed=False,
                total_seconds=1800,
                units=1,
            )
        ],
        generated_at=now,
    )

    payload = builder.build_claim_bundle(state, summary)

    assert payload["resourceType"] == "Bundle"
    assert payload["type"] == "message"
    resource_types = {entry["resource"]["resourceType"] for entry in payload["entry"]}
    assert resource_types == {"MessageHeader", "Patient", "Organization", "Claim"}


def test_fhir_export_persists_to_storage() -> None:
    container = ServiceContainer()
    bundle = container.region_registry.resolve("SA")
    builder = NphiesClaimBundleBuilder(bundle)
    storage = InMemoryObjectStorage()
    now = now_utc()
    state = SessionState(
        session_id="sa-export",
        billing_region="SA",
        payer_id="payer-1",
        member_id="member-1",
    )
    summary = BillingSummary(
        session_id="sa-export",
        total_minutes=0,
        total_units=0,
        generated_at=now,
    )

    artifact = FhirExportService().export_session(state, summary, builder, storage)

    assert artifact.storage_uri is not None
    assert storage.exists(artifact.storage_key or "")
    assert artifact.byte_size > 0
    assert artifact.checksum_sha256
