from __future__ import annotations

from datetime import timedelta

from medexa.api.dependencies import ServiceContainer
from medexa.application.session_start_service import SessionStartService
from medexa.application.session_enrichment_service import SessionEnrichmentService
from medexa.domain.events import CodeConflictFound, PreAuthViolationFound
from medexa.schemas import SessionState, TranscriptChunk
from medexa.utils.time import now_utc


def test_sa_session_start_captures_pre_auth_snapshot() -> None:
    container = ServiceContainer()
    runtime = container.runtime_for_region("SA")
    state = SessionState(
        session_id="sa-start",
        billing_region="SA",
        payer_id="payer-1",
        member_id="member-1",
    )
    result = SessionStartService(SessionEnrichmentService()).bootstrap(
        state,
        runtime,
        runtime.pre_auth_exchange,
    )

    assert result.pre_auth_snapshot is not None
    assert result.pre_auth_snapshot.provider == "nphies"
    assert result.pre_auth_snapshot.eligible is True
    assert result.state.pre_auth_snapshot is not None


def test_sa_chunk_mri_raises_pre_auth_live_alert() -> None:
    container = ServiceContainer()
    runtime = container.runtime_for_region("SA")
    now = now_utc()
    state = SessionState(
        session_id="sa-mri",
        billing_region="SA",
        payer_id="payer-1",
        member_id="member-1",
    )
    chunk = TranscriptChunk(
        session_id="sa-mri",
        chunk_id="chunk-1",
        text="Patient scheduled for MRI of the lumbar spine today.",
        start_ts=0,
        end_ts=10,
        sequence=1,
    )

    result = runtime.path_a_processor.process(state, chunk, now)

    assert any(alert.alert_type == "pre_auth_required" for alert in result.new_alerts)
    assert any(isinstance(event, PreAuthViolationFound) for event in result.events)


def test_ae_chunk_without_emirate_conflict_alert() -> None:
    container = ServiceContainer()
    runtime = container.runtime_for_region("AE")
    now = now_utc()
    state = SessionState(
        session_id="ae-conflict",
        billing_region="AE",
        payer_id="payer-1",
        member_id="member-1",
    )
    chunk = TranscriptChunk(
        session_id="ae-conflict",
        chunk_id="chunk-1",
        text="Continue therapy session.",
        start_ts=0,
        end_ts=10,
        sequence=1,
    )

    result = runtime.path_a_processor.process(state, chunk, now)

    assert any(alert.alert_type == "billing_conflict" for alert in result.new_alerts)
    assert any(isinstance(event, CodeConflictFound) for event in result.events)


def test_ae_doh_session_start_routes_to_shafafiya() -> None:
    container = ServiceContainer()
    runtime = container.runtime_for_region("AE")
    state = SessionState(
        session_id="ae-doh",
        billing_region="AE",
        emirate="DOH",
        payer_id="payer-1",
        member_id="member-1",
    )
    result = container.session_start.bootstrap(state, runtime, runtime.pre_auth_exchange)

    assert result.exchange_routing is not None
    assert result.exchange_routing["exchange_platform"] == "Shafafiya"
