from __future__ import annotations

import logging
from pathlib import Path


from medexa.adapters.events.in_process_bus import InProcessEventBus
from medexa.adapters.guardrails.local_guardrails import LocalGuardrails
from medexa.adapters.realtime.factory import build_realtime_adapter
from medexa.adapters.realtime.in_process_broker import InProcessBroker
from medexa.adapters.storage.in_memory_storage import InMemoryObjectStorage
from medexa.adapters.deep_evaluation.no_op import NoOpDeepEvaluation
from medexa.application.documentation_review_builder import DocumentationReviewBuilder
from medexa.application.documentation_service import DocumentationService
from medexa.application.session_context_builder import SessionContextBuilder
from medexa.application.chunk_ingest_service import ChunkIngestService
from medexa.application.fhir_export_service import FhirExportService
from medexa.application.finalize_session_orchestrator import FinalizeSessionOrchestrator
from medexa.application.pre_auth_reconciliation_service import PreAuthReconciliationService
from medexa.application.session_enrichment_service import SessionEnrichmentService
from medexa.application.session_start_service import SessionStartService
from medexa.application.pre_auth_refresh_service import PreAuthRefreshService
from medexa.application.regional_path_a_service import RegionalPathAService
from medexa.application.path_b_worker import PathBWorker
from medexa.application.event_handlers import (
    PathAEventDispatcher,
    register_event_handlers,
)
from medexa.application.path_a_clinical_snapshot import PathAClinicalSnapshotBuilder
from medexa.application.path_a_processor import PathAProcessor
from medexa.application.path_b_trigger_evaluator import PathBTriggerEvaluator
from medexa.config import settings
from medexa.core.billing_engine import BillingEngine
from medexa.core.billing_summary_builder import BillingSummaryBuilder
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.core.entity_extractor import EntityExtractor
from medexa.core.insights_builder import InsightsBuilder
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.core.suggestion_generator import SuggestionGenerator
from medexa.core.ambient_diarization_resolver import AmbientDiarizationResolver
from medexa.core.ambient_speaker_diarizer import AmbientSpeakerDiarizer
from medexa.core.deepgram_speaker_mapper import DeepgramSpeakerRoleMapper
from medexa.core.speaker_role_classifier import SpeakerRoleClassifier, format_labeled_utterance
from medexa.core.transcript_processor import TranscriptProcessor
from medexa.loaders.cpt_aoc_info_loader import CptAocInfoLoader
from medexa.loaders.cpt_general_info_loader import CptGeneralInfoLoader
from medexa.loaders.cpt_icd10_info_loader import CptIcd10InfoLoader
from medexa.loaders.cpt_mue_info_loader import CptMueInfoLoader
from medexa.loaders.cpt_ptp_info_loader import CptPtpInfoLoader
from medexa.loaders.pt_ot_slp_billing_categories_loader import PtOtSlpBillingCategoriesLoader
from medexa.loaders.mue_limits_loader import MueLimitsLoader
from medexa.regions.factory import (
    build_pre_auth_exchange_adapter,
    build_pre_auth_validator,
    build_regional_conflict_checker,
)
from medexa.regions.registry import RegionRegistry
from medexa.regions.runtime import RegionRuntime
from medexa.regions.sa.detection.detector import SaFileDetector
from medexa.regions.sa.detection.entity_extractor import SaEntityExtractor
from medexa.regions.sa.detection.metadata import SaSbsMetadataRegistry
from medexa.regions.us.loaders import (
    UsBodyRegionNormalizer,
    UsCptMetadataRegistry,
    UsCptRuleIndex,
    UsIcdLookupLoader,
    UsNcciRulesLoader,
)
from medexa.services.clinical_analyzer import RulesClinicalAnalyzer
from medexa.services.providers import (
    build_clinical_analyzer,
    build_clinical_assistant,
    build_documentation_service,
    build_soap_generator,
    build_summary_generator,
    build_transcription_provider,
)
from medexa.state import (
    DynamoDbSessionStateRepository,
    FileSessionStateRepository,
    InMemorySessionStateRepository,
    SessionStateRepository,
)


_dep_logger = logging.getLogger("medexa.api.dependencies")


class ServiceContainer:
    def __init__(self, config_dir: Path | None = None, cpt_files_dir: Path | None = None) -> None:
        cfg = config_dir or settings.config_dir
        cpt_dir = cpt_files_dir or settings.cpt_files_dir

        # S3 config loader — warm cache at startup when config_source is s3.
        self.s3_config_loader = None
        if getattr(settings, "config_source", "local") == "s3":
            try:
                from medexa.aws.s3_config_loader import S3ConfigLoader

                self.s3_config_loader = S3ConfigLoader(
                    bucket=settings.s3_bucket or "medexa-storage",
                    region_name=settings.aws_region,
                )
                count = self.s3_config_loader.warm_cache("regions/")
                _dep_logger.info(
                    "s3_config_loader_ready",
                    extra={"extra_fields": {"files_cached": count}},
                )
            except Exception:
                _dep_logger.warning(
                    "s3_config_loader_init_failed_falling_back_to_local",
                    exc_info=True,
                )
                self.s3_config_loader = None

        self.region_registry = RegionRegistry(
            cfg, cpt_dir, s3_loader=self.s3_config_loader
        )
        self.default_region_bundle = self.region_registry.resolve("US")
        self.eight_minute_calculator = EightMinuteRuleCalculator()
        self.timer_engine = BillingTimerEngine()
        codes_dir = self.default_region_bundle.asset_paths.region_dir / "codes"
        self.cpt_general_info = CptGeneralInfoLoader(codes_dir / "cpt_general_info 4.json")
        self.cpt_icd10_info = CptIcd10InfoLoader(codes_dir / "cpt_icd10_info 2.json")
        self.cpt_aoc_info = CptAocInfoLoader(codes_dir / "cpt_aoc_info 6.json")
        self.cpt_mue_info = CptMueInfoLoader(codes_dir / "cpt_mue_info 4.json")
        self.pt_ot_slp_categories = PtOtSlpBillingCategoriesLoader(codes_dir / "pt_ot_slp_billing_categories 5.json")
        self.ptp_loader = CptPtpInfoLoader(codes_dir / "cpt_ptp_info 4.json")
        self.hybrid_cpt_index = UsCptRuleIndex(self.default_region_bundle)
        self.cpt_metadata = UsCptMetadataRegistry(self.default_region_bundle)
        self.mue_limits = MueLimitsLoader(cpt_dir)
        self.region_normalizer = UsBodyRegionNormalizer(self.default_region_bundle)
        self.ncci_loader = UsNcciRulesLoader(self.default_region_bundle)
        self.icd_loader = UsIcdLookupLoader(self.default_region_bundle)
        self.ncci_checker = NcciConflictChecker(self.ptp_loader)
        self.suggestion_generator = SuggestionGenerator(
            self.cpt_metadata,
            settings.suggestion_cooldown_seconds,
            ncci_checker=self.ncci_checker,
        )
        self.speaker_role_classifier = SpeakerRoleClassifier()
        self.ambient_speaker_diarizer = AmbientSpeakerDiarizer(self.speaker_role_classifier)
        self.deepgram_speaker_mapper = DeepgramSpeakerRoleMapper(self.speaker_role_classifier)
        self.ambient_diarization_resolver = AmbientDiarizationResolver(
            voice_diarizer=self.ambient_speaker_diarizer,
            deepgram_mapper=self.deepgram_speaker_mapper,
        )
        self._region_runtimes: dict[str, RegionRuntime] = {}
        default_runtime = self.runtime_for_region("US")
        self.entity_extractor = EntityExtractor(self.hybrid_cpt_index, self.region_normalizer)
        self.transcript_processor = default_runtime.transcript_processor
        self.insights_builder = default_runtime.insights_builder
        self.billing_summary_builder = default_runtime.billing_summary_builder
        self.rules_clinical_analyzer = default_runtime.rules_clinical_analyzer
        self.clinical_analyzer = build_clinical_analyzer(
            settings,
            entity_extractor=self.entity_extractor,
            cpt_metadata_loader=self.cpt_metadata,
            icd_loader=self.icd_loader,
            ncci_loader=self.ncci_loader,
            region_normalizer=self.region_normalizer,
        )
        self.soap_generator = build_soap_generator(settings)
        self.summary_generator = build_summary_generator(settings)
        self.transcription_provider = build_transcription_provider(settings)
        self.guardrails = LocalGuardrails()
        self.documentation_service = build_documentation_service(
            settings, self.guardrails, icd_loader=self.icd_loader
        )

        self.chunk_ingest = ChunkIngestService()
        self.session_enrichment = SessionEnrichmentService()
        self.session_start = SessionStartService(self.session_enrichment)
        self.pre_auth_refresh = PreAuthRefreshService()
        self.fhir_export_service = FhirExportService()
        self.pre_auth_reconciliation_service = PreAuthReconciliationService()
        self.finalize_orchestrator = FinalizeSessionOrchestrator(
            documentation_service=self.documentation_service,
            context_builder=SessionContextBuilder(self.icd_loader),
            review_builder=DocumentationReviewBuilder(),
            timer_engine=self.timer_engine,
            fhir_export_service=self.fhir_export_service,
            pre_auth_reconciliation=self.pre_auth_reconciliation_service,
            pre_auth_refresh=self.pre_auth_refresh,
            deep_evaluation=NoOpDeepEvaluation(),
        )
        self._memory_object_storage = InMemoryObjectStorage()
        self.path_a_processor = default_runtime.path_a_processor
        self.path_a_snapshot = default_runtime.path_a_snapshot

        self.live_broker = InProcessBroker()
        self.event_bus = InProcessEventBus()
        self.realtime = build_realtime_adapter(settings, self.live_broker)
        self.session_repo: SessionStateRepository = self._build_repository()
        self.clinical_assistant = build_clinical_assistant(settings, self.guardrails)
        self.path_b_trigger_evaluator = PathBTriggerEvaluator(
            settings.path_b_interval_seconds, config_dir=cfg
        )
        self.path_b_worker = PathBWorker(
            settings=settings,
            session_repo=self.session_repo,
            assistant=self.clinical_assistant,
            realtime=self.realtime,
        )
        self.object_storage = self._build_object_storage()

        self.path_a_dispatcher = PathAEventDispatcher(
            self.event_bus,
            self.path_b_trigger_evaluator,
            self.realtime,
            self.session_repo,
        )
        register_event_handlers(self.event_bus, path_b_worker=self.path_b_worker)

    @staticmethod
    def _build_repository() -> SessionStateRepository:
        if settings.use_dynamodb:
            return DynamoDbSessionStateRepository(
                table_name=settings.dynamodb_table_name,
                region_name=settings.aws_region,
            )
        if settings.session_persist_dir:
            return FileSessionStateRepository(settings.session_persist_dir)
        return InMemorySessionStateRepository()

    @staticmethod
    def _build_object_storage():
        bucket = settings.s3_bucket or settings.transcribe_s3_bucket
        if not bucket:
            return None
        from medexa.adapters.aws.s3_storage import S3ObjectStorage

        return S3ObjectStorage(bucket, region_name=settings.aws_region)

    def export_object_storage(self):
        return self.object_storage or self._memory_object_storage

    def runtime_for_state(self, billing_region: str) -> RegionRuntime:
        return self.runtime_for_region(billing_region)

    def runtime_for_region(self, billing_region: str) -> RegionRuntime:
        bundle = self.region_registry.resolve(billing_region)
        cached = self._region_runtimes.get(bundle.billing_region)
        if cached is not None:
            return cached

        # US Path A uses Hybrid CPT/NCCI loaders. SA Path A uses file-based SBS /
        # ICD-10-AM detection (no LLM). AE keeps US extractors with GCC profile flags.
        data_bundle = self.default_region_bundle
        cpt_index = UsCptRuleIndex(data_bundle)
        cpt_metadata = UsCptMetadataRegistry(data_bundle)
        region_normalizer = UsBodyRegionNormalizer(data_bundle)
        ncci_loader = UsNcciRulesLoader(data_bundle)
        icd_loader = UsIcdLookupLoader(data_bundle)
        entity_extractor: EntityExtractor | SaEntityExtractor = EntityExtractor(
            cpt_index, region_normalizer
        )
        suggestion_generator = self.suggestion_generator
        sa_extractor: SaEntityExtractor | None = None

        if bundle.billing_region == "SA":
            sa_detector = SaFileDetector.from_bundle(bundle)
            sa_extractor = SaEntityExtractor(sa_detector)
            entity_extractor = sa_extractor
            cpt_metadata = SaSbsMetadataRegistry(sa_detector.catalog)  # type: ignore[assignment]
            suggestion_generator = SuggestionGenerator(
                cpt_metadata,
                settings.suggestion_cooldown_seconds,
                ncci_checker=None,
            )

        transcript_processor = TranscriptProcessor(entity_extractor, suggestion_generator)
        ncci_checker = NcciConflictChecker(self.ptp_loader)
        rules_analyzer = RulesClinicalAnalyzer(
            entity_extractor=entity_extractor if isinstance(entity_extractor, EntityExtractor) else EntityExtractor(cpt_index, region_normalizer),
            cpt_metadata_loader=cpt_metadata,
            icd_loader=icd_loader,
            ncci_loader=ncci_loader,
            region_normalizer=region_normalizer,
            enable_ncci=bundle.profile.uses_ncci,
        )
        billing_engine = BillingEngine(
            self.timer_engine,
            self.eight_minute_calculator,
            cpt_metadata,
            ncci_checker,
            cpt_general_info=self.cpt_general_info,
            billing_category=self.pt_ot_slp_categories,
            use_eight_minute_rule=bundle.profile.uses_eight_minute_rule,
        )
        insights_builder = InsightsBuilder(
            billing_engine,
            ncci_checker,
            cpt_metadata,
            self.timer_engine,
            enable_ncci=bundle.profile.uses_ncci,
        )
        billing_summary_builder = BillingSummaryBuilder(billing_engine)
        pre_auth_validator = build_pre_auth_validator(bundle.billing_region, bundle)
        regional_path_a = None
        if bundle.billing_region in {"SA", "AE"}:
            regional_path_a = RegionalPathAService(
                bundle=bundle,
                pre_auth_validator=pre_auth_validator,
                conflict_checker=build_regional_conflict_checker(bundle.billing_region, bundle),
            )
        path_a_processor = PathAProcessor(
            transcript_processor,
            insights_builder,
            ncci_checker,
            cpt_metadata,
            self.timer_engine,
            enable_ncci=bundle.profile.uses_ncci,
            regional_path_a=regional_path_a,
            sa_extractor=sa_extractor,
        )
        path_a_snapshot = PathAClinicalSnapshotBuilder(
            rules_analyzer,
            icd_loader,
            ncci_loader,
            cpt_metadata,
        )
        pre_auth_validator = build_pre_auth_validator(bundle.billing_region, bundle)
        runtime = RegionRuntime(
            bundle=bundle,
            profile=bundle.profile,
            transcript_processor=transcript_processor,
            cpt_metadata=cpt_metadata,
            insights_builder=insights_builder,
            billing_engine=billing_engine,
            billing_summary_builder=billing_summary_builder,
            rules_clinical_analyzer=rules_analyzer,
            path_a_processor=path_a_processor,
            path_a_snapshot=path_a_snapshot,
            pre_auth_validator=pre_auth_validator,
            pre_auth_exchange=build_pre_auth_exchange_adapter(bundle.billing_region),
            sa_catalog=sa_extractor.detector.catalog if sa_extractor is not None else None,
        )
        self._region_runtimes[bundle.billing_region] = runtime
        return runtime


_container: ServiceContainer | None = None


def get_container() -> ServiceContainer:
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container
