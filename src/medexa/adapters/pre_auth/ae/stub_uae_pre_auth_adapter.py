from __future__ import annotations

from dataclasses import dataclass

from medexa.schemas import SessionState


@dataclass(frozen=True)
class StubUaePreAuthAdapter:
    """Phase 3 stub for UAE payer authorization exchange."""

    def check_eligibility(self, state: SessionState) -> dict[str, object]:
        return {
            "status": "stub",
            "provider": "uae_payer",
            "billing_region": state.billing_region,
            "emirate": state.emirate,
            "payer_id": state.payer_id,
            "member_id": state.member_id,
            "eligible": all([state.emirate, state.payer_id, state.member_id]),
        }

    def submit_prior_auth(self, state: SessionState, payload: dict[str, object]) -> dict[str, object]:
        return {
            "status": "stub",
            "provider": "uae_payer",
            "emirate": state.emirate,
            "reference": state.pre_auth_reference,
            "accepted": False,
            "detail": "Live UAE payer submission is not enabled in Phase 3.",
            "payload_keys": sorted(payload.keys()),
        }
