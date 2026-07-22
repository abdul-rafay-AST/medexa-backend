from __future__ import annotations

from medexa.adapters.pre_auth.ae.eligibility_router import UaeEligibilityRouter
from medexa.adapters.pre_auth.ae.stub_uae_pre_auth_adapter import StubUaePreAuthAdapter
from medexa.adapters.pre_auth.sa.stub_nphies_adapter import StubNphiesAdapter
from medexa.adapters.fhir.ae.fhir_r4_builder import UaeFhirR4Builder
from medexa.adapters.fhir.sa.claim_bundle_builder import NphiesClaimBundleBuilder
from medexa.adapters.fhir.sa.eligibility_bundle_builder import NphiesEligibilityBundleBuilder
from medexa.adapters.fhir.sa.priorauth_bundle_builder import NphiesPriorAuthBundleBuilder
from medexa.domain.billing_region import BillingRegion
from medexa.ports.conflict_checker_port import RegionalConflictCheckerPort
from medexa.ports.fhir_export_port import (
    EligibilityFhirExportPort,
    FhirExportPort,
    PriorAuthFhirExportPort,
)
from medexa.ports.pre_auth import PreAuthExchangePort, PreAuthValidatorPort
from medexa.regions.ae.rules.pre_auth_validator import UaeConflictChecker, UaePreAuthValidator
from medexa.regions.bundle import RegionBundle
from medexa.regions.sa.rules.pre_auth_validator import SaudiConflictChecker, SaudiPreAuthValidator


def build_pre_auth_validator(
    billing_region: BillingRegion,
    bundle: RegionBundle,
) -> PreAuthValidatorPort | None:
    if billing_region == "SA":
        return SaudiPreAuthValidator(bundle)
    if billing_region == "AE":
        return UaePreAuthValidator(bundle)
    return None


def build_regional_conflict_checker(
    billing_region: BillingRegion,
    bundle: RegionBundle,
) -> RegionalConflictCheckerPort | None:
    if billing_region == "SA":
        return SaudiConflictChecker(bundle)
    if billing_region == "AE":
        return UaeConflictChecker(bundle)
    return None


def build_pre_auth_exchange_adapter(
    billing_region: BillingRegion,
) -> PreAuthExchangePort | None:
    if billing_region == "SA":
        return StubNphiesAdapter()
    if billing_region == "AE":
        return StubUaePreAuthAdapter()
    return None


def build_uae_eligibility_router(bundle: RegionBundle) -> UaeEligibilityRouter:
    return UaeEligibilityRouter(bundle)


def build_fhir_exporter(bundle: RegionBundle) -> FhirExportPort | None:
    if bundle.billing_region == "SA":
        return NphiesClaimBundleBuilder(bundle)
    if bundle.billing_region == "AE":
        return UaeFhirR4Builder(bundle)
    return None


def build_priorauth_fhir_exporter(bundle: RegionBundle) -> PriorAuthFhirExportPort | None:
    """Saudi NPHIES prior-auth request builder. UAE has no equivalent yet."""
    if bundle.billing_region == "SA":
        return NphiesPriorAuthBundleBuilder(bundle)
    return None


def build_eligibility_fhir_exporter(bundle: RegionBundle) -> EligibilityFhirExportPort | None:
    """Saudi NPHIES coverage eligibility request builder."""
    if bundle.billing_region == "SA":
        return NphiesEligibilityBundleBuilder(bundle)
    return None
