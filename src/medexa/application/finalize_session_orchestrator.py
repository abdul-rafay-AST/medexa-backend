from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from medexa.api import contracts as c
from medexa.application.documentation_review_builder import DocumentationReviewBuilder
from medexa.application.documentation_service import DocumentationService
from medexa.application.fhir_export_service import FhirExportService
from medexa.application.pre_auth_reconciliation_service import PreAuthReconciliationService
from medexa.application.pre_auth_refresh_service import PreAuthRefreshService
from medexa.application.session_context_builder import SessionContextBuilder
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.domain.audit import AuditAction, ComplianceAuditEntry
from medexa.domain.documentation_review import DocumentationReviewReport
from medexa.domain.fhir_export import FhirExportArtifact, PreAuthReconciliationReport
from medexa.ports.deep_evaluation_port import DeepEvaluationPort
from medexa.regions.factory import build_fhir_exporter
from medexa.regions.runtime import RegionRuntime
from medexa.schemas import BillingSummary, SessionState


@dataclass(frozen=True)
class FinalizeSessionResult:
    state: SessionState
    billing_summary: BillingSummary
    fhir_export: FhirExportArtifact | None = None
    pre_auth_reconciliation: PreAuthReconciliationReport | None = None
    documentation_review: DocumentationReviewReport | None = None
    idempotent_replay: bool = False


@dataclass
class FinalizeSessionOrchestrator:
    """Saga orchestrator for Path C — one-shot deep documentation at session end."""

    documentation_service: DocumentationService
    context_builder: SessionContextBuilder
    review_builder: DocumentationReviewBuilder
    timer_engine: BillingTimerEngine
    fhir_export_service: FhirExportService
    pre_auth_reconciliation: PreAuthReconciliationService
    pre_auth_refresh: PreAuthRefreshService
    deep_evaluation: DeepEvaluationPort | None = None

    def finalize(
        self,
        state: SessionState,
        runtime: RegionRuntime,
        body: c.FinalizeSessionRequest,
        *,
        now: datetime,
        object_storage,
    ) -> FinalizeSessionResult:
        if self._is_idempotent_replay(state):
            billing_summary = runtime.billing_summary_builder.build(state, now)
            return FinalizeSessionResult(
                state=state,
                billing_summary=billing_summary,
                fhir_export=state.fhir_export,
                pre_auth_reconciliation=state.pre_auth_reconciliation,
                documentation_review=state.documentation_review,
                idempotent_replay=True,
            )

        if body.transcript.strip():
            state.transcript_text = body.transcript.strip()
        if body.total_seconds > 0:
            state.client_elapsed_seconds = body.total_seconds

        self.timer_engine.stop_all_running(state, now)
        state.status = "ended"
        state.finalized_at = now
        state.last_updated = now

        if runtime.pre_auth_exchange is not None:
            self.pre_auth_refresh.refresh(state, runtime.pre_auth_exchange)

        context = self.context_builder.build(state)
        documentation = self.documentation_service.generate(state, context)
        state.soap = documentation.soap
        state.patient_summary.summary = documentation.patient_summary

        if self.deep_evaluation is not None:
            _ = self.deep_evaluation.evaluate(state.session_id)

        billing_summary = runtime.billing_summary_builder.build(state, now)
        reconciliation = self.pre_auth_reconciliation.build(state)
        if reconciliation is not None:
            state.pre_auth_reconciliation = reconciliation

        review = self.review_builder.build(state, billing_summary)
        state.documentation_review = review

        fhir_artifact: FhirExportArtifact | None = None
        if runtime.profile.fhir_export:
            exporter = build_fhir_exporter(runtime.bundle)
            if exporter is not None:
                fhir_artifact = self.fhir_export_service.export_session(
                    state,
                    billing_summary,
                    exporter,
                    object_storage,
                )
                state.fhir_export = fhir_artifact
                state.audit_log.append(
                    ComplianceAuditEntry(
                        entry_id=str(uuid.uuid4()),
                        session_id=state.session_id,
                        action=AuditAction.FHIR_EXPORTED,
                        actor="system",
                        detail=f"FHIR bundle {fhir_artifact.bundle_id} exported",
                    )
                )

        state.audit_log.append(
            ComplianceAuditEntry(
                entry_id=str(uuid.uuid4()),
                session_id=state.session_id,
                action=AuditAction.SESSION_FINALIZED,
                actor="system",
                detail=(
                    f"Session finalized for region {state.billing_region} "
                    f"via {documentation.source}"
                ),
            )
        )
        return FinalizeSessionResult(
            state=state,
            billing_summary=billing_summary,
            fhir_export=fhir_artifact,
            pre_auth_reconciliation=reconciliation,
            documentation_review=review,
        )

    @staticmethod
    def _is_idempotent_replay(state: SessionState) -> bool:
        return (
            state.status == "ended"
            and state.finalized_at is not None
            and state.documentation_review is not None
        )
