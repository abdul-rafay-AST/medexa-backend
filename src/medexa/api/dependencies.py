from __future__ import annotations

from pathlib import Path

from medexa.config import settings
from medexa.core.billing_summary_builder import BillingSummaryBuilder
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.core.entity_extractor import EntityExtractor
from medexa.core.insights_builder import InsightsBuilder
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.core.suggestion_generator import SuggestionGenerator
from medexa.core.transcript_processor import TranscriptProcessor
from medexa.loaders.activity_synonym_loader import ActivitySynonymLoader
from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.loaders.cpt_lookup_loader import CptLookupLoader
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.loaders.ncci_rules_loader import NcciRulesLoader
from medexa.state import (
    DynamoDbSessionStateRepository,
    InMemorySessionStateRepository,
    SessionStateRepository,
)


class ServiceContainer:
    """Builds and holds all singletons. Rule files are loaded ONCE here (golden
    rule #3); request handlers receive ready-to-use engine objects."""

    def __init__(self, config_dir: Path | None = None) -> None:
        cfg = config_dir or settings.config_dir

        # Loaders (load-once, in memory).
        self.cpt_loader = CptLookupLoader(cfg / "cpt_lookup.json")
        self.cpt_metadata_loader = CptMetadataLoader(cfg / "cpt_metadata.json")
        self.synonym_loader = ActivitySynonymLoader(cfg / "activity_synonyms.json")
        self.region_normalizer = BodyRegionNormalizer(cfg / "body_regions.json")
        self.ncci_loader = NcciRulesLoader(cfg / "ncci_rules.json")

        # Core engine.
        self.entity_extractor = EntityExtractor(
            synonym_loader=self.synonym_loader,
            region_normalizer=self.region_normalizer,
            cpt_loader=self.cpt_loader,
        )
        self.eight_minute_calculator = EightMinuteRuleCalculator()
        self.ncci_checker = NcciConflictChecker(self.ncci_loader)
        self.timer_engine = BillingTimerEngine()
        self.suggestion_generator = SuggestionGenerator(
            self.cpt_metadata_loader, settings.suggestion_cooldown_seconds
        )
        self.transcript_processor = TranscriptProcessor(
            self.entity_extractor, self.suggestion_generator
        )
        self.insights_builder = InsightsBuilder(
            self.eight_minute_calculator,
            self.ncci_checker,
            self.cpt_metadata_loader,
            self.timer_engine,
        )
        self.billing_summary_builder = BillingSummaryBuilder(
            self.eight_minute_calculator,
            self.cpt_metadata_loader,
            self.timer_engine
        )

        # Storage: in-memory locally (no AWS), DynamoDB when explicitly enabled.
        self.session_repo: SessionStateRepository = self._build_repository()

    @staticmethod
    def _build_repository() -> SessionStateRepository:
        if settings.use_dynamodb:
            return DynamoDbSessionStateRepository(
                table_name=settings.dynamodb_table_name,
                region_name=settings.aws_region,
            )
        return InMemorySessionStateRepository()


_container: ServiceContainer | None = None


def get_container() -> ServiceContainer:
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container
