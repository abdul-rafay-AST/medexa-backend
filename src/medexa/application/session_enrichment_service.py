from __future__ import annotations

import uuid
from dataclasses import dataclass

from medexa.ports.pre_auth import PreAuthValidatorPort
from medexa.schemas import Alert, SessionState


@dataclass(frozen=True)
class SessionEnrichmentResult:
    alerts: list[Alert]
    routing: dict[str, object] | None = None


class SessionEnrichmentService:
    """Applies region-specific session onboarding checks at start time."""

    def enrich(
        self,
        state: SessionState,
        validator: PreAuthValidatorPort | None,
        *,
        routing: dict[str, object] | None = None,
    ) -> SessionEnrichmentResult:
        if validator is None:
            return SessionEnrichmentResult(alerts=[], routing=routing)

        alerts: list[Alert] = []
        for violation in validator.validate_session_fields(state):
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    session_id=state.session_id,
                    alert_type="session_field_missing",
                    severity="high" if violation.severity == "error" else "medium",
                    message=violation.message,
                )
            )
        for violation in validator.validate_pre_auth(state):
            alerts.append(
                Alert(
                    alert_id=str(uuid.uuid4()),
                    session_id=state.session_id,
                    alert_type="pre_auth_required",
                    severity="high" if violation.severity == "high" else "medium",
                    message=violation.message,
                    policy_id=violation.policy_id,
                )
            )
        return SessionEnrichmentResult(alerts=alerts, routing=routing)
