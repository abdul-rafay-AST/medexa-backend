from __future__ import annotations

from dataclasses import dataclass

from medexa.domain.fhir_export import PreAuthReconciliationItem, PreAuthReconciliationReport
from medexa.schemas import SessionState


@dataclass(frozen=True)
class PreAuthReconciliationService:
    """Summarizes pre-auth posture at session end for GCC regions."""

    def build(self, state: SessionState) -> PreAuthReconciliationReport | None:
        if state.billing_region not in {"SA", "AE"}:
            return None

        open_items: list[PreAuthReconciliationItem] = []
        for alert in state.alerts:
            if alert.alert_type not in {"pre_auth_required", "billing_conflict", "session_field_missing"}:
                continue
            if alert.status in {"approved", "ignored"}:
                continue
            open_items.append(
                PreAuthReconciliationItem(
                    alert_id=alert.alert_id,
                    alert_type=alert.alert_type,
                    policy_id=alert.policy_id,
                    rule_id=alert.rule_id,
                    severity=alert.severity,
                    message=alert.message,
                    status="open",
                )
            )

        snapshot_status = state.pre_auth_snapshot.status if state.pre_auth_snapshot else None
        has_reference = bool(state.pre_auth_reference and state.pre_auth_reference.strip())
        reconciled = has_reference and not open_items

        return PreAuthReconciliationReport(
            session_id=state.session_id,
            billing_region=state.billing_region,
            snapshot_status=snapshot_status,
            pre_auth_reference=state.pre_auth_reference,
            open_violations=open_items,
            reconciled=reconciled,
        )
