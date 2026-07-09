from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from medexa.utils.time import now_utc

PreAuthStatus = Literal["unknown", "not_required", "approved", "pending", "denied", "stub"]


class PreAuthSnapshot(BaseModel):
    """Immutable payer authorization context captured at session start.

  Phase 3 stores a stub snapshot from regional adapters. Phase 5 replaces the
  adapter with live NPHIES / UAE eligibility without changing session shape.
    """

    provider: str
    billing_region: str
    status: PreAuthStatus = "unknown"
    payer_id: str | None = None
    member_id: str | None = None
    pre_auth_reference: str | None = None
    emirate: str | None = None
    eligible: bool | None = None
    exchange_routing: dict[str, Any] | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=now_utc)
