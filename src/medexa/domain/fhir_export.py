from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from medexa.utils.time import now_utc


class FhirExportArtifact(BaseModel):
    """Metadata for a persisted FHIR R4 claim package."""

    session_id: str
    billing_region: str
    profile_id: str
    bundle_id: str
    content_type: str = "application/fhir+json"
    storage_uri: str | None = None
    storage_key: str | None = None
    byte_size: int = 0
    checksum_sha256: str | None = None
    exported_at: datetime = Field(default_factory=now_utc)


class PreAuthReconciliationItem(BaseModel):
    alert_id: str
    alert_type: str
    policy_id: str | None = None
    rule_id: str | None = None
    severity: str
    message: str
    status: Literal["open", "resolved", "waived"] = "open"


class PreAuthReconciliationReport(BaseModel):
    session_id: str
    billing_region: str
    snapshot_status: str | None = None
    pre_auth_reference: str | None = None
    open_violations: list[PreAuthReconciliationItem] = Field(default_factory=list)
    reconciled: bool = False
    generated_at: datetime = Field(default_factory=now_utc)
