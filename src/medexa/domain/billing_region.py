from __future__ import annotations

from typing import Literal

BillingRegion = Literal["US", "SA", "AE"]

DEFAULT_BILLING_REGION: BillingRegion = "US"

SUPPORTED_BILLING_REGIONS: frozenset[BillingRegion] = frozenset({"US", "SA", "AE"})


def normalize_billing_region(value: str | None) -> BillingRegion:
    if not value:
        return DEFAULT_BILLING_REGION
    upper = value.strip().upper()
    if upper not in SUPPORTED_BILLING_REGIONS:
        raise ValueError(f"Unsupported billing region: {value}")
    return upper  # type: ignore[return-value]
