from __future__ import annotations

from dataclasses import dataclass

from medexa.application.path_a_clinical_snapshot import PathAClinicalSnapshotBuilder
from medexa.application.path_a_processor import PathAProcessor
from medexa.core.billing_engine import BillingEngine
from medexa.core.billing_summary_builder import BillingSummaryBuilder
from medexa.core.insights_builder import InsightsBuilder
from medexa.core.transcript_processor import TranscriptProcessor
from medexa.ports.cpt_metadata import CptMetadataPort
from medexa.ports.pre_auth import PreAuthExchangePort, PreAuthValidatorPort
from medexa.regions.bundle import RegionBundle
from medexa.regions.profile_loader import RegionProfile
from medexa.regions.sa.detection.catalog import SaBillingCatalog
from medexa.services.clinical_analyzer import RulesClinicalAnalyzer


@dataclass(frozen=True)
class RegionRuntime:
    bundle: RegionBundle
    profile: RegionProfile
    transcript_processor: TranscriptProcessor
    cpt_metadata: CptMetadataPort
    insights_builder: InsightsBuilder
    billing_engine: BillingEngine
    billing_summary_builder: BillingSummaryBuilder
    rules_clinical_analyzer: RulesClinicalAnalyzer
    path_a_processor: PathAProcessor
    path_a_snapshot: PathAClinicalSnapshotBuilder
    pre_auth_validator: PreAuthValidatorPort | None = None
    pre_auth_exchange: PreAuthExchangePort | None = None
    sa_catalog: SaBillingCatalog | None = None
