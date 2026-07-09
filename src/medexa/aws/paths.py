from __future__ import annotations

from medexa.domain.billing_region import BillingRegion


class S3Prefixes:
  TRANSCRIBE = "transcribe"
  EXPORTS = "exports"
  AUDIT = "audit"
  REGIONS = "regions"


def transcribe_audio_key(session_id: str, filename: str) -> str:
    return f"{S3Prefixes.TRANSCRIBE}/{session_id}/{filename}"


def export_bundle_key(session_id: str, filename: str) -> str:
    return f"{S3Prefixes.EXPORTS}/{session_id}/{filename}"


def fhir_export_key(billing_region: str, session_id: str, filename: str) -> str:
    normalized = billing_region.lower()
    return f"{S3Prefixes.EXPORTS}/{normalized}/{session_id}/{filename}"


def audit_export_key(session_id: str, filename: str) -> str:
    return f"{S3Prefixes.AUDIT}/{session_id}/{filename}"


def region_config_key(billing_region: BillingRegion, relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").lstrip("/")
    return f"{S3Prefixes.REGIONS}/{billing_region.lower()}/{normalized}"
