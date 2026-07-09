from __future__ import annotations

import uuid
from dataclasses import dataclass

from medexa.core.insights_builder import _alert_key
from medexa.ports.conflict_checker_port import RegionalConflictCheckerPort
from medexa.ports.pre_auth import PreAuthValidatorPort
from medexa.regions.bundle import RegionBundle
from medexa.schemas import Alert, SessionState


@dataclass
class RegionalPathAService:
    """GCC Path A enrichment: pre-auth and billing conflict alerts during live ingest."""

    bundle: RegionBundle
    pre_auth_validator: PreAuthValidatorPort | None = None
    conflict_checker: RegionalConflictCheckerPort | None = None

    def reconcile_chunk(
        self,
        state: SessionState,
        chunk_text: str,
        prior_alert_keys: set[tuple[tuple[str, ...], str | None]],
    ) -> list[Alert]:
        if state.billing_region not in {"SA", "AE"}:
            return []

        new_alerts: list[Alert] = []
        if self.pre_auth_validator is not None:
            for violation in self.pre_auth_validator.check_transcript_text(chunk_text):
                alert = Alert(
                    alert_id=str(uuid.uuid4()),
                    session_id=state.session_id,
                    alert_type="pre_auth_required",
                    severity="high" if violation.severity == "high" else "medium",
                    message=violation.message,
                    policy_id=violation.policy_id,
                )
                key = _alert_key(alert)
                if key not in prior_alert_keys:
                    new_alerts.append(alert)
                    prior_alert_keys.add(key)

        if self.conflict_checker is not None:
            for finding in self.conflict_checker.evaluate_transcript(state, chunk_text):
                alert = Alert(
                    alert_id=str(uuid.uuid4()),
                    session_id=state.session_id,
                    alert_type="billing_conflict",
                    severity="high" if finding.severity in {"error", "high"} else "medium",
                    message=finding.message,
                    rule_id=finding.rule_id,
                )
                key = _alert_key(alert)
                if key not in prior_alert_keys:
                    new_alerts.append(alert)
                    prior_alert_keys.add(key)

            for finding in self.conflict_checker.evaluate(state):
                alert = Alert(
                    alert_id=str(uuid.uuid4()),
                    session_id=state.session_id,
                    alert_type="billing_conflict",
                    severity="high" if finding.severity in {"error", "high"} else "medium",
                    message=str(finding.message),
                    rule_id=finding.rule_id,
                )
                key = _alert_key(alert)
                if key not in prior_alert_keys:
                    new_alerts.append(alert)
                    prior_alert_keys.add(key)

        return new_alerts
