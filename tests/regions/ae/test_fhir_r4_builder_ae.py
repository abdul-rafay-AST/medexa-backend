from __future__ import annotations

from datetime import timedelta

from medexa.adapters.fhir.ae.fhir_r4_builder import UaeFhirR4Builder
from medexa.api.dependencies import ServiceContainer
from medexa.schemas import BillingLineItem, BillingSummary, SessionState, TimerSegment
from medexa.utils.time import now_utc


def test_uae_bundle_tags_emirate_and_claim() -> None:
    container = ServiceContainer()
    bundle = container.region_registry.resolve("AE")
    builder = UaeFhirR4Builder(bundle)
    now = now_utc()
    state = SessionState(
        session_id="ae-fhir",
        billing_region="AE",
        emirate="DOH",
        payer_id="payer-1",
        member_id="member-1",
        timer_segments=[
            TimerSegment(
                segment_id="seg-1",
                cpt_code="therapy_session",
                body_region="shoulder_left",
                start_time=now - timedelta(minutes=20),
                stop_time=now,
                accumulated_seconds=1200,
            )
        ],
    )
    summary = BillingSummary(
        session_id="ae-fhir",
        total_minutes=20,
        total_units=1,
        line_items=[
            BillingLineItem(
                cpt_code="therapy_session",
                display_name="Therapy Session",
                timed=False,
                total_seconds=1200,
                units=1,
            )
        ],
        generated_at=now,
    )

    payload = builder.build_claim_bundle(state, summary)

    assert payload["resourceType"] == "Bundle"
    assert payload["type"] == "collection"
    claim = next(entry["resource"] for entry in payload["entry"] if entry["resource"]["resourceType"] == "Claim")
    emirate_tags = claim["meta"]["tag"]
    assert emirate_tags[0]["code"] == "DOH"
    assert claim["extension"][0]["valueString"] == "shafafiya-xml-bridge"
