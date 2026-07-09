from __future__ import annotations

from datetime import datetime

import pytest

from medexa.application.documentation_review_builder import DocumentationReviewBuilder
from medexa.application.documentation_service import DocumentationService
from medexa.application.finalize_session_orchestrator import FinalizeSessionOrchestrator
from medexa.application.pre_auth_reconciliation_service import PreAuthReconciliationService
from medexa.application.pre_auth_refresh_service import PreAuthRefreshService
from medexa.application.session_context_builder import SessionContextBuilder
from medexa.adapters.bedrock.documentation_generator import RulesDocumentationGenerator
from medexa.adapters.deep_evaluation.no_op import NoOpDeepEvaluation
from medexa.api import contracts as c
from medexa.api.dependencies import ServiceContainer
from medexa.application.fhir_export_service import FhirExportService
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.schemas import SessionState, TranscriptChunk


@pytest.fixture
def us_runtime():
    return ServiceContainer().runtime_for_region("US")


def test_session_context_builder_uses_all_chunks() -> None:
    state = SessionState(
        session_id="ctx-1",
        transcript_chunks=[
            TranscriptChunk(
                session_id="ctx-1",
                chunk_id="c1",
                text="first segment",
                start_ts=0,
                end_ts=10,
                sequence=0,
            ),
            TranscriptChunk(
                session_id="ctx-1",
                chunk_id="c2",
                text="second segment",
                start_ts=10,
                end_ts=25,
                sequence=1,
            ),
        ],
    )
    context = SessionContextBuilder().build(state)
    assert "first segment" in context.full_transcript
    assert "second segment" in context.full_transcript


def test_finalize_orchestrator_is_idempotent(us_runtime) -> None:
    timer_engine = BillingTimerEngine()
    orchestrator = FinalizeSessionOrchestrator(
        documentation_service=DocumentationService(RulesDocumentationGenerator()),
        context_builder=SessionContextBuilder(),
        review_builder=DocumentationReviewBuilder(),
        timer_engine=timer_engine,
        fhir_export_service=FhirExportService(),
        pre_auth_reconciliation=PreAuthReconciliationService(),
        pre_auth_refresh=PreAuthRefreshService(),
        deep_evaluation=NoOpDeepEvaluation(),
    )
    state = SessionState(session_id="fin-1", patient_name="Alex Patient")
    now = datetime(2026, 1, 1, 12, 0, 0)
    body = c.FinalizeSessionRequest(transcript="Full therapy session transcript.", total_seconds=1200)

    first = orchestrator.finalize(state, us_runtime, body, now=now, object_storage=None)
    second = orchestrator.finalize(first.state, us_runtime, body, now=now, object_storage=None)

    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.state.soap.generated is True
    assert second.documentation_review is not None
    assert second.state.documentation_review is not None
