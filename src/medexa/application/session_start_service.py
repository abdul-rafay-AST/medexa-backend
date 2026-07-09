from __future__ import annotations

from dataclasses import dataclass

from medexa.application.session_enrichment_service import SessionEnrichmentService
from medexa.domain.pre_authorization import PreAuthSnapshot
from medexa.ports.pre_auth import PreAuthExchangePort
from medexa.regions.factory import build_uae_eligibility_router
from medexa.regions.runtime import RegionRuntime
from medexa.schemas import SessionState


@dataclass(frozen=True)
class SessionStartResult:
    state: SessionState
    pre_auth_snapshot: PreAuthSnapshot | None
    exchange_routing: dict[str, object] | None = None


class SessionStartService:
    """Region Phase 3 session bootstrap: snapshot, routing, and onboarding alerts."""

    def __init__(self, enrichment: SessionEnrichmentService) -> None:
        self._enrichment = enrichment

    def bootstrap(
        self,
        state: SessionState,
        runtime: RegionRuntime,
        exchange_adapter: PreAuthExchangePort | None,
    ) -> SessionStartResult:
        exchange_routing = None
        if state.billing_region == "AE" and state.emirate:
            exchange_routing = build_uae_eligibility_router(runtime.bundle).route(state)

        snapshot = self._capture_pre_auth_snapshot(state, exchange_adapter, exchange_routing)
        if snapshot is not None:
            state.pre_auth_snapshot = snapshot

        enrichment = self._enrichment.enrich(
            state,
            runtime.pre_auth_validator,
            routing=exchange_routing,
        )
        state.alerts.extend(enrichment.alerts)
        return SessionStartResult(
            state=state,
            pre_auth_snapshot=snapshot,
            exchange_routing=exchange_routing,
        )

    @staticmethod
    def _capture_pre_auth_snapshot(
        state: SessionState,
        exchange_adapter: PreAuthExchangePort | None,
        exchange_routing: dict[str, object] | None,
    ) -> PreAuthSnapshot | None:
        if state.billing_region not in {"SA", "AE"}:
            return None
        if exchange_adapter is None:
            return None

        response = exchange_adapter.check_eligibility(state)
        status = "approved" if response.get("eligible") else "stub"
        return PreAuthSnapshot(
            provider=str(response.get("provider", state.billing_region.lower())),
            billing_region=state.billing_region,
            status=status,
            payer_id=state.payer_id,
            member_id=state.member_id,
            pre_auth_reference=state.pre_auth_reference,
            emirate=state.emirate,
            eligible=bool(response.get("eligible")) if response.get("eligible") is not None else None,
            exchange_routing=exchange_routing,
            raw=response,
        )
