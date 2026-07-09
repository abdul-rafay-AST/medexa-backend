from __future__ import annotations

from pathlib import Path

from medexa.regions import RegionRegistry


def test_registry_resolves_all_supported_profiles() -> None:
    registry = RegionRegistry(Path("config"), Path("MEDEXA CPT FILES"))

    us = registry.resolve("US")
    sa = registry.resolve("SA")
    ae = registry.resolve("AE")

    assert us.profile.display_name == "United States"
    assert us.profile.uses_ncci is True
    assert sa.profile.display_name == "Saudi Arabia"
    assert sa.profile.pre_auth_provider == "nphies"
    assert ae.profile.display_name == "United Arab Emirates"
    assert ae.profile.fhir_export is True


def test_us_bundle_uses_legacy_files_until_phase1_asset_copy() -> None:
    registry = RegionRegistry(Path("config"), Path("MEDEXA CPT FILES"))
    us = registry.resolve("US")

    cpt_lookup = us.asset_path("codes/cpt_lookup.json")
    body_regions = us.asset_path("clinical/body_regions.json")

    assert cpt_lookup.name == "cpt_lookup.json"
    assert "regions" in cpt_lookup.parts and "us" in cpt_lookup.parts
    assert body_regions.name == "body_regions.json"
    assert "regions" in body_regions.parts and "us" in body_regions.parts
