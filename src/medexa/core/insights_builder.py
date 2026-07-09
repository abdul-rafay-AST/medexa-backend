from __future__ import annotations

from datetime import datetime

from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.ports.cpt_metadata import CptMetadataPort
from medexa.schemas import (
    Alert,
    CurrentCptSnapshot,
    InsightsPanel,
    SessionState,
)


def _alert_key(alert: Alert) -> tuple[tuple[str, ...], str | None]:
    return (tuple(sorted(alert.cpt_codes)), alert.body_region)


class InsightsBuilder:
    """Assembles the right-panel snapshot from session state.

    Healthcare rules enforced here:
      * Only ``timed`` CPTs feed the 8-minute rule; untimed modalities never
        accrue time-based units.
      * NCCI alerts are advisory and reconciled by identity so a clinician's
        approve/reject decision is never overwritten on the next refresh.
    """

    def __init__(
        self,
        eight_minute_calculator: EightMinuteRuleCalculator,
        ncci_checker: NcciConflictChecker,
        cpt_metadata_loader: CptMetadataPort,
        timer_engine: BillingTimerEngine,
        *,
        enable_eight_minute_rule: bool = True,
        enable_ncci: bool = True,
    ):
        self._calc = eight_minute_calculator
        self._ncci = ncci_checker
        self._meta = cpt_metadata_loader
        self._timer = timer_engine
        self._enable_eight_minute_rule = enable_eight_minute_rule
        self._enable_ncci = enable_ncci

    def build(self, state: SessionState, now: datetime) -> InsightsPanel:
        seconds_by_cpt: dict[str, int] = {}
        current: CurrentCptSnapshot | None = None

        for seg in state.timer_segments:
            sec = self._timer.accumulated_seconds(seg, now)
            seconds_by_cpt[seg.cpt_code] = seconds_by_cpt.get(seg.cpt_code, 0) + sec
            if seg.stop_time is None:
                current = CurrentCptSnapshot(
                    code=seg.cpt_code,
                    label=self._meta.get_display_name(seg.cpt_code),
                    duration_sec=sec,
                    body_region=seg.body_region,
                    is_billable=seg.is_billable,
                    status="in_progress" if state.status == "active" else "paused",
                )

        # Gate: only timed CPTs participate in the 8-minute rule.
        timed_minutes = {
            cpt: sec // 60
            for cpt, sec in seconds_by_cpt.items()
            if self._meta.is_timed(cpt)
        }
        eight_min = (
            self._calc.calculate(timed_minutes)
            if self._enable_eight_minute_rule and timed_minutes
            else None
        )

        # NCCI across ALL segments in the session (a finished service still
        # conflicts with a later one on the same region), reconciled by identity.
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
            eight_minute_rule=eight_min,
            alerts=state.alerts,
            session_timer_sec=sum(seconds_by_cpt.values()),
            last_updated=now,
        )
