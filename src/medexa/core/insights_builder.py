from __future__ import annotations

from datetime import datetime

from medexa.core.billing_engine import BillingEngine
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.schemas import (
    Alert,
    CurrentCptSnapshot,
    InsightsPanel,
    SessionState,
)
from medexa.ports.cpt_metadata import CptMetadataPort
from medexa.core.billing_timer_engine import BillingTimerEngine


def _alert_key(alert: Alert) -> tuple[tuple[str, ...], str | None]:
    return (tuple(sorted(alert.cpt_codes)), alert.body_region)


class InsightsBuilder:
    """Assembles the right-panel snapshot from session state."""

    def __init__(
        self,
        billing_engine: BillingEngine,
        ncci_checker: NcciConflictChecker,
        cpt_metadata_loader: CptMetadataPort,
        timer_engine: BillingTimerEngine,
        *,
        enable_ncci: bool = True,
    ):
        self._billing = billing_engine
        self._ncci = ncci_checker
        self._meta = cpt_metadata_loader
        self._timer = timer_engine
        self._enable_ncci = enable_ncci

    def build(self, state: SessionState, now: datetime) -> InsightsPanel:
        metrics = self._billing.compute_metrics(state, now)
        current: CurrentCptSnapshot | None = None

        for seg in reversed(state.timer_segments):
            if seg.stop_time is None:
                sec = self._timer.accumulated_seconds(seg, now)
                current = CurrentCptSnapshot(
                    code=seg.cpt_code,
                    label=self._meta.get_display_name(seg.cpt_code),
                    duration_sec=sec,
                    body_region=seg.body_region,
                    is_billable=seg.is_billable,
                    status="in_progress" if state.status == "active" else "paused",
                )
                break

        segments = [(seg.cpt_code, seg.body_region) for seg in state.timer_segments]
        if self._enable_ncci:
            fresh = self._ncci.check_conflicts(state.session_id, segments)
            existing_keys = {_alert_key(a) for a in state.alerts}
            for alert in fresh:
                if _alert_key(alert) not in existing_keys:
                    state.alerts.append(alert)
                    existing_keys.add(_alert_key(alert))

        return InsightsPanel(
            session_id=state.session_id,
            current_cpt=current,
            live_extractions=state.detected_entities,
            eight_minute_rule=metrics.eight_minute_rule,
            alerts=state.alerts,
            session_timer_sec=metrics.timed_pool_seconds,
            last_updated=now,
        )
