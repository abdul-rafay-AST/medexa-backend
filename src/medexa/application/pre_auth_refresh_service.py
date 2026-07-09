from __future__ import annotations

from medexa.domain.pre_authorization import PreAuthSnapshot
from medexa.ports.pre_auth import PreAuthExchangePort
from medexa.schemas import SessionState


class PreAuthRefreshService:
    """Phase 3 stub refresh for payer authorization context."""

    def refresh(
        self,
        state: SessionState,
        exchange_adapter: PreAuthExchangePort | None,
    ) -> PreAuthSnapshot | None:
        if exchange_adapter is None or state.billing_region not in {"SA", "AE"}:
            return state.pre_auth_snapshot

        response = exchange_adapter.check_eligibility(state)
        snapshot = PreAuthSnapshot(
            provider=str(response.get("provider", state.billing_region.lower())),
            billing_region=state.billing_region,
            status="approved" if response.get("eligible") else "stub",
            payer_id=state.payer_id,
            member_id=state.member_id,
            pre_auth_reference=state.pre_auth_reference,
            emirate=state.emirate,
            eligible=bool(response.get("eligible")) if response.get("eligible") is not None else None,
            exchange_routing=state.pre_auth_snapshot.exchange_routing if state.pre_auth_snapshot else None,
            raw=response,
        )
        state.pre_auth_snapshot = snapshot
        return snapshot
