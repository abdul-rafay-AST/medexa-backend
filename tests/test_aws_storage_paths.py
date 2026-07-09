from __future__ import annotations

import pytest

from medexa.aws.paths import export_bundle_key, fhir_export_key, region_config_key, transcribe_audio_key
from medexa.aws.s3_setup import default_bucket_candidates, default_bucket_name, fallback_bucket_name
from medexa.domain.billing_region import normalize_billing_region


def test_normalize_billing_region_defaults_us():
    assert normalize_billing_region(None) == "US"
    assert normalize_billing_region("sa") == "SA"


def test_normalize_billing_region_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_billing_region("UK")


def test_s3_keys_are_region_scoped_for_config_only():
    assert transcribe_audio_key("sess-1", "audio.wav") == "transcribe/sess-1/audio.wav"
    assert export_bundle_key("sess-1", "claim.json") == "exports/sess-1/claim.json"
    assert fhir_export_key("SA", "sess-1", "claim-bundle.json") == "exports/sa/sess-1/claim-bundle.json"
    assert region_config_key("SA", "codes/cchi.json") == "regions/sa/codes/cchi.json"
    assert region_config_key("AE", "rules/edits.json") == "regions/ae/rules/edits.json"


def test_default_bucket_names_prefer_human_name_with_safe_fallbacks():
    assert default_bucket_name("staging", "527097962658") == "medexa-storage"
    assert fallback_bucket_name("staging", "527097962658") == "medexa-storage-staging-527097962658"
    assert default_bucket_candidates("staging", "527097962658") == [
        "medexa-storage",
        "medexa-storage-staging",
        "medexa-storage-staging-527097962658",
    ]
