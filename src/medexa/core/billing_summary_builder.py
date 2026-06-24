from __future__ import annotations

from datetime import datetime

from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.schemas import BillingLineItem, BillingSummary, SessionState


class BillingSummaryBuilder:
    """Post-session billing review (prototype 'Billing Intelligence' screen).

    Timed CPTs are unitized via the 8-minute rule; untimed modalities bill
    exactly 1 unit per session (CMS rule). This is advisory output for a human
    reviewer to verify before a claim is submitted.
    """

    def __init__(
        self,
        eight_minute_calculator: EightMinuteRuleCalculator,
        cpt_metadata_loader: CptMetadataLoader,
        timer_engine: BillingTimerEngine,
    ):
        self._calc = eight_minute_calculator
        self._meta = cpt_metadata_loader
        self._timer = timer_engine

    def build(self, state: SessionState, now: datetime) -> BillingSummary:
        seconds_by_cpt = self._timer.seconds_by_cpt(state, now)

        timed_minutes = {
            cpt: sec // 60
            for cpt, sec in seconds_by_cpt.items()
            if self._meta.is_timed(cpt)
        }
        eight_min = self._calc.calculate(timed_minutes) if timed_minutes else None

        line_items: list[BillingLineItem] = []
        total_units = 0
        for cpt, sec in sorted(seconds_by_cpt.items()):
            timed = self._meta.is_timed(cpt)
            if timed:
                units = eight_min.units_by_cpt.get(cpt, 0) if eight_min else 0
            else:
                # Untimed modality: 1 unit per session if it was performed at all.
                units = 1 if sec > 0 else 0
            total_units += units
            line_items.append(
                BillingLineItem(
                    cpt_code=cpt,
                    display_name=self._meta.get_display_name(cpt),
                    timed=timed,
                    total_seconds=sec,
                    units=units,
                )
            )
        return BillingSummary(
            session_id=state.session_id,
            total_minutes=sum(sec // 60 for sec in seconds_by_cpt.values()),
            total_units=total_units,
            line_items=line_items,
            eight_minute_rule=eight_min,
            alerts=state.alerts,
            generated_at=now,
        )
