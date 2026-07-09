from __future__ import annotations

from dataclasses import dataclass

from medexa.schemas import SessionState


@dataclass(frozen=True)
class StubNphiesAdapter:
    """Phase 3 stub for Saudi NPHIES exchange. No outbound network calls."""

    def check_eligibility(self, state: SessionState) -> dict[str, object]:
        return {
            "status": "stub",
            "provider": "nphies",
            "billing_region": state.billing_region,
            "payer_id": state.payer_id,
            "member_id": state.member_id,
            "eligible": state.payer_id is not None and state.member_id is not None,
        }

    def submit_prior_auth(self, state: SessionState, payload: dict[str, object]) -> dict[str, object]:
        return {
            "status": "stub",
            "provider": "nphies",
            "reference": state.pre_auth_reference,
            "accepted": False,
            "detail": "Live NPHIES submission is not enabled in Phase 3.",
            "payload_keys": sorted(payload.keys()),
        }
