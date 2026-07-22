"""Central billing calculations for live and finalized sessions.

Encodes CMS outpatient therapy rules used in Medexa:
  * Only billable, timed CPT minutes pool for the 8-minute rule.
  * Untimed modalities bill 1 unit per session when performed.
  * NCCI column-2 codes are suppressed unless the conflict alert is approved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.ports.cpt_metadata import (
    BillingCategoryPort,
    CptGeneralInfoPort,
    CptMetadataPort,
)
from medexa.schemas import (
    Alert,
    BillingLineItem,
    BillingSummary,
    EightMinuteRuleResult,
    SessionState,
)


@dataclass(frozen=True)
class BillingMetrics:
    """Live billing numbers exposed to the API and insights panel."""

    timed_pool_seconds: int
    timed_minutes_by_cpt: dict[str, int]
    billable_seconds_by_cpt: dict[str, int]
    running_segment_seconds: int
    eight_minute_rule: EightMinuteRuleResult | None
    total_units: int
    seconds_to_next_unit: int


class BillingEngine:
    def __init__(
        self,
        timer_engine: BillingTimerEngine,
        eight_minute_calculator: EightMinuteRuleCalculator,
        cpt_metadata: CptMetadataPort,
        ncci_checker: NcciConflictChecker,
        cpt_general_info: CptGeneralInfoPort | None = None,
        billing_category: BillingCategoryPort | None = None,
        *,
        use_eight_minute_rule: bool = True,
    ) -> None:
        self._timer = timer_engine
        self._calc = eight_minute_calculator
        self._meta = cpt_metadata
        self._ncci = ncci_checker
        self._general_info = cpt_general_info
        self._category = billing_category
        self._use_eight_minute_rule = use_eight_minute_rule

    def _get_cpt_billing_rule(self, cpt_code: str) -> str | None:
        """Resolve billingRule for a CPT by checking category then general info.

        Checks billing category first (more specific), then falls back to
        general info if no category match is found.
        """
        rule = None
        if self._category is not None:
            rule = self._category.get_billing_rule(cpt_code)
        if rule is None and self._general_info is not None:
            rule = self._general_info.get_billing_rule(cpt_code)
        return rule

    @staticmethod
    def _is_untimed_billing_rule(billing_rule: str | None) -> bool:
        """Check if a billing rule is an untimed/non-time-based rule.

        These rules bill a fixed number of units (typically 1) regardless
        of time spent and should not contribute to timed pool calculations.
        """
        if billing_rule is None:
            return False
        return billing_rule in (
            "untimed_per_day",
            "untimed_per_session",
            "untimed_per_procedure",
            "untimed_per_encounter",
            "untimed_per_episode",
            "area_based",
            "time_band_select",
        )

    def billable_seconds_by_cpt(self, state: SessionState, now: datetime) -> dict[str, int]:
        totals: dict[str, int] = {}
        for seg in state.timer_segments:
            if not seg.is_billable:
                continue
            sec = self._timer.accumulated_seconds(seg, now)
            totals[seg.cpt_code] = totals.get(seg.cpt_code, 0) + sec
        return totals

    def timed_minutes_by_cpt(self, state: SessionState, now: datetime) -> dict[str, int]:
        minutes: dict[str, int] = {}
        for seg in state.timer_segments:
            if not seg.is_billable:
                continue
            cpt = seg.cpt_code
            billing_rule = self._get_cpt_billing_rule(cpt)
            if billing_rule is not None:
                if self._is_untimed_billing_rule(billing_rule):
                    continue
            elif not self._meta.is_timed(cpt):
                continue
            sec = self._timer.accumulated_seconds(seg, now)
            minutes[cpt] = minutes.get(cpt, 0) + sec // 60
        return minutes

    def timed_pool_seconds(self, state: SessionState, now: datetime) -> int:
        return sum(
            sec
            for cpt, sec in self.billable_seconds_by_cpt(state, now).items()
            if self._meta.is_timed(cpt)
        )

    def compute_metrics(self, state: SessionState, now: datetime) -> BillingMetrics:
        timed_minutes = self.timed_minutes_by_cpt(state, now)
        eight_min = (
            self._calc.calculate(timed_minutes)
            if self._use_eight_minute_rule and timed_minutes
            else None
        )
        seconds_to_next = eight_min.seconds_to_next_unit if eight_min else 0
        total_units = eight_min.total_units if eight_min else 0
        return BillingMetrics(
            timed_pool_seconds=self.timed_pool_seconds(state, now),
            timed_minutes_by_cpt=timed_minutes,
            billable_seconds_by_cpt=self.billable_seconds_by_cpt(state, now),
            running_segment_seconds=self._timer.running_segment_seconds(state, now),
            eight_minute_rule=eight_min,
            total_units=total_units,
            seconds_to_next_unit=seconds_to_next,
        )

    def build_summary(self, state: SessionState, now: datetime) -> BillingSummary:
        metrics = self.compute_metrics(state, now)
        eight_min = metrics.eight_minute_rule
        line_items: list[BillingLineItem] = []
        total_units = 0

        for cpt, sec in sorted(metrics.billable_seconds_by_cpt.items()):
            billing_rule = self._get_cpt_billing_rule(cpt)

            if billing_rule is not None and self._is_untimed_billing_rule(billing_rule):
                units = 1 if sec > 0 else 0
            elif self._meta.is_timed(cpt) and self._use_eight_minute_rule and eight_min is not None:
                units = eight_min.units_by_cpt.get(cpt, 0)
            else:
                units = 1 if sec > 0 else 0

            timed = self._meta.is_timed(cpt)
            if billing_rule is not None and self._is_untimed_billing_rule(billing_rule):
                timed = False

            line_items.append(
                BillingLineItem(
                    cpt_code=cpt,
                    display_name=self._meta.get_display_name(cpt),
                    timed=timed,
                    total_seconds=sec,
                    units=units,
                )
            )
            total_units += units

        self._apply_ncci_billing_adjustments(state, line_items)
        total_units = sum(item.units for item in line_items)

        return BillingSummary(
            session_id=state.session_id,
            total_minutes=sum(metrics.timed_minutes_by_cpt.values()),
            total_units=total_units,
            line_items=line_items,
            eight_minute_rule=eight_min,
            alerts=state.alerts,
            generated_at=now,
        )

    def _apply_ncci_billing_adjustments(
        self, state: SessionState, line_items: list[BillingLineItem]
    ) -> None:
        """Suppress column-2 (bundled) CPT units when NCCI conflict is unresolved.

        CMS PTP edits: without an allowed modifier, the bundled code is not
        separately payable. Units allocated to the bundled code transfer to the
        column-1 (paying) code in the edit pair.
        """
        by_code = {item.cpt_code: item for item in line_items}

        for alert in state.alerts:
            if alert.alert_type != "ncci_conflict" or alert.status == "approved":
                continue
            if len(alert.cpt_codes) != 2:
                continue
            code_a, code_b = sorted(alert.cpt_codes)
            rule = self._ncci.check_conflict(code_a, code_b)
            if not rule:
                continue

            bundled = rule.get("bundled_code") or rule["cpt_a"]
            paying = rule.get("payable_code") or rule["cpt_b"]
            bundled_item = by_code.get(bundled)
            paying_item = by_code.get(paying)
            if bundled_item is None or bundled_item.units == 0:
                continue

            transfer = bundled_item.units
            bundled_item.units = 0
            if paying_item is not None:
                paying_item.units += transfer
