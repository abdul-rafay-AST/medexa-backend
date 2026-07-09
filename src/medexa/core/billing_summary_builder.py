from __future__ import annotations

from datetime import datetime

from medexa.core.billing_engine import BillingEngine
from medexa.schemas import BillingSummary, SessionState


class BillingSummaryBuilder:
    """Post-session billing review (prototype 'Billing Intelligence' screen)."""

    def __init__(self, billing_engine: BillingEngine) -> None:
        self._engine = billing_engine

    @property
    def engine(self) -> BillingEngine:
        return self._engine

    def build(self, state: SessionState, now: datetime) -> BillingSummary:
        return self._engine.build_summary(state, now)
