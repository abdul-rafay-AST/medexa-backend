"""SA file-based SBS / ICD-10-AM Path A detection tests (no LLM)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from medexa.application.path_a_processor import PathAProcessor
from medexa.config import settings
from medexa.core.billing_engine import BillingEngine
from medexa.core.billing_timer_engine import BillingTimerEngine
from medexa.core.eight_minute_rule import EightMinuteRuleCalculator
from medexa.core.insights_builder import InsightsBuilder
from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.core.suggestion_generator import SuggestionGenerator
from medexa.core.transcript_processor import TranscriptProcessor
from medexa.regions.registry import RegionRegistry
from medexa.regions.sa.detection.catalog import load_sa_catalog
from medexa.regions.sa.detection.detector import CONFIDENCE_THRESHOLD, SaFileDetector
from medexa.regions.sa.detection.entity_extractor import SaEntityExtractor
from medexa.regions.sa.detection.mapping import validate_sbs_icd_mapping
from medexa.regions.sa.detection.metadata import SaSbsMetadataRegistry
from medexa.regions.us.loaders import UsNcciRulesLoader
from medexa.schemas import SessionState, TranscriptChunk


@pytest.fixture(scope="module")
def sa_bundle():
    registry = RegionRegistry(settings.config_dir, settings.cpt_files_dir)
    return registry.resolve("SA")


@pytest.fixture(scope="module")
def sa_detector(sa_bundle):
    return SaFileDetector.from_bundle(sa_bundle)


def test_sa_catalog_resolves_required_assets(sa_bundle):
    catalog = load_sa_catalog(sa_bundle)
    assert catalog.sbs_lookup, "medexa_sbs_lookup.json missing or empty"
    assert catalog.icd_lookup, "medexa_icd10_lookup.json missing or empty"
    assert catalog.sbs_icd_mapping, "sbs_icd10_mapping.json missing or empty"
    sbs_path = sa_bundle.asset_paths.resolve("codes/medexa_sbs_lookup.json")
    assert Path(sbs_path).exists()


def test_speech_audiometry_detects_sbs_above_threshold(sa_detector):
    text = "We will perform speech audiometry and check how softly you can hear words."
    result = sa_detector.detect_from_transcript(text)
    codes = {h.code: h for h in result.sbs_codes}
    assert "11306-00-30" in codes
    assert codes["11306-00-30"].confidence >= CONFIDENCE_THRESHOLD


def test_mapping_valid_when_linked_icd_present(sa_detector):
    catalog = sa_detector.catalog
    sbs = "11306-00-30"
    linked = next(iter(catalog.sbs_icd_mapping.get(sbs) or []), None)
    assert linked, "expected Direct_ICD10_Codes for speech audiometry"
    results = validate_sbs_icd_mapping([sbs], [linked], catalog)
    assert len(results) == 1
    assert results[0].status == "valid"
    assert results[0].matched_icd == linked


def test_mapping_pending_when_icd_missing(sa_detector):
    catalog = sa_detector.catalog
    sbs = "11306-00-30"
    results = validate_sbs_icd_mapping([sbs], [], catalog)
    assert results[0].status == "pending_review"


def test_sa_path_a_merges_sbs_and_icd_insights(sa_bundle, sa_detector):
    extractor = SaEntityExtractor(sa_detector)
    metadata = SaSbsMetadataRegistry(sa_detector.catalog)
    suggestions = SuggestionGenerator(metadata, cooldown_seconds=60, ncci_checker=None)
    processor = TranscriptProcessor(extractor, suggestions)
    us_bundle = RegionRegistry(settings.config_dir, settings.cpt_files_dir).resolve("US")
    ncci = NcciConflictChecker(UsNcciRulesLoader(us_bundle))
    timers = BillingTimerEngine()
    billing = BillingEngine(
        timers,
        EightMinuteRuleCalculator(),
        metadata,
        ncci,
        use_eight_minute_rule=False,
    )
    insights = InsightsBuilder(billing, ncci, metadata, timers, enable_ncci=False)
    path_a = PathAProcessor(
        processor,
        insights,
        ncci,
        metadata,
        timers,
        enable_ncci=False,
        sa_extractor=extractor,
    )

    state = SessionState(session_id="sa-1", patient_id="p1", billing_region="SA")
    chunk = TranscriptChunk(
        session_id="sa-1",
        chunk_id="c1",
        text="We will perform speech audiometry and check how softly you can hear words.",
        start_ts=0.0,
        end_ts=5.0,
        sequence=1,
    )
    now = datetime.now(timezone.utc)
    result = path_a.process(state, chunk, now)

    assert any(e.possible_cpt == "11306-00-30" for e in result.entities)
    sbs_insights = [i for i in state.insights if i.type == "detected" and i.code == "11306-00-30"]
    assert sbs_insights
    assert sbs_insights[0].validation_status in {"valid", "pending_review", "valid_no_crosswalk"}


def test_approve_ignore_preserves_insight_status(sa_bundle, sa_detector):
    extractor = SaEntityExtractor(sa_detector)
    metadata = SaSbsMetadataRegistry(sa_detector.catalog)
    suggestions = SuggestionGenerator(metadata, cooldown_seconds=60, ncci_checker=None)
    processor = TranscriptProcessor(extractor, suggestions)
    us_bundle = RegionRegistry(settings.config_dir, settings.cpt_files_dir).resolve("US")
    ncci = NcciConflictChecker(UsNcciRulesLoader(us_bundle))
    timers = BillingTimerEngine()
    billing = BillingEngine(
        timers,
        EightMinuteRuleCalculator(),
        metadata,
        ncci,
        use_eight_minute_rule=False,
    )
    insights = InsightsBuilder(billing, ncci, metadata, timers, enable_ncci=False)
    path_a = PathAProcessor(
        processor,
        insights,
        ncci,
        metadata,
        timers,
        enable_ncci=False,
        sa_extractor=extractor,
    )
    state = SessionState(session_id="sa-2", patient_id="p1", billing_region="SA")
    chunk = TranscriptChunk(
        session_id="sa-2",
        chunk_id="c1",
        text="We will perform speech audiometry and check how softly you can hear words.",
        start_ts=0.0,
        end_ts=5.0,
        sequence=1,
    )
    path_a.process(state, chunk, datetime.now(timezone.utc))
    sbs = next(i for i in state.insights if i.type == "detected" and i.code == "11306-00-30")
    sbs.status = "approved"
    # Re-detect same code — merge must keep approved status
    path_a.process(
        state,
        TranscriptChunk(
            session_id="sa-2",
            chunk_id="c2",
            text="Speech audiometry test completed.",
            start_ts=5.0,
            end_ts=10.0,
            sequence=2,
        ),
        datetime.now(timezone.utc),
    )
    kept = next(i for i in state.insights if i.insight_id == sbs.insight_id)
    assert kept.status == "approved"


def test_us_path_a_unchanged_by_sa_wiring(sa_bundle):
    """US sessions keep CPT EntityExtractor; SA sessions use SaEntityExtractor."""
    from medexa.core.entity_extractor import EntityExtractor
    from medexa.regions.us.loaders import UsBodyRegionNormalizer, UsCptRuleIndex

    us_bundle = RegionRegistry(settings.config_dir, settings.cpt_files_dir).resolve("US")
    us_extractor = EntityExtractor(UsCptRuleIndex(us_bundle), UsBodyRegionNormalizer(us_bundle))
    sa_extractor = SaEntityExtractor(SaFileDetector.from_bundle(sa_bundle))

    us_entities = us_extractor.extract(
        "Performed therapeutic exercise for the right knee.",
        "us-chunk",
    )
    sa_entities = sa_extractor.extract(
        "We will perform speech audiometry and check how softly you can hear words.",
        "sa-chunk",
    )

    assert any(e.possible_cpt == "11306-00-30" for e in sa_entities)
    assert isinstance(us_extractor, EntityExtractor)
    assert not isinstance(us_extractor, SaEntityExtractor)
    assert not any(e.possible_cpt == "11306-00-30" for e in us_entities)


def test_catalog_indexes_symptom_inference_fields(sa_bundle):
    """_index_icd_phrases must index symptom_trigger_phrases + required_symptom_groups."""
    catalog = load_sa_catalog(sa_bundle)
    all_indexed_codes = set()
    for codes in catalog.icd_keyword_index.values():
        all_indexed_codes.update(codes)
    assert len(all_indexed_codes) > 100, "ICD index should cover many codes"
    unique_path = sa_bundle.asset_paths.resolve("codes/unique_icd10_codes.json")
    assert Path(unique_path).exists()
    assert catalog.icd_descriptions, "Unique + AM ICD descriptions should load"


def test_icd_symptom_auto_detect_above_threshold(sa_detector):
    """Explicit diagnosis trigger → auto-detect with confidence ≥ 80 (hard)."""
    from medexa.regions.sa.detection.icd_symptom_matcher import (
        map_hit_to_confidence,
        match_icd_symptoms,
    )

    hits = match_icd_symptoms(
        sa_detector.catalog.icd_lookup,
        "patient diagnosed with shoulder stiffness",
    )
    assert hits, "should detect at least one ICD after data sync"
    _support, conf, auto = map_hit_to_confidence(hits[0])
    assert auto is True
    assert conf >= 80


def test_icd_review_candidate_below_threshold(sa_detector):
    """Symptom pattern with unconfirmed diagnosis → review candidate (soft if none)."""
    result = sa_detector.detect_from_transcript(
        "patient reports knee swelling and difficulty walking"
    )
    for hit in result.icd10_am_review:
        assert hit.review_only is True
        assert hit.confidence < 80


def test_is_timed_package_codes(sa_bundle):
    """Package SBS codes (98010/98014/98016) must be timed."""
    detector = SaFileDetector.from_bundle(sa_bundle)
    metadata = SaSbsMetadataRegistry(detector.catalog)
    assert metadata.is_timed("98014-00-10") is True
    assert metadata.is_timed("98016-00-30") is True
    assert metadata.is_timed("98010-00-50") is True
    assert metadata.is_timed("11306-00-30") is False


def test_mapping_pending_message_has_no_example_icd_list(sa_detector):
    catalog = sa_detector.catalog
    sbs = "11306-00-30"
    results = validate_sbs_icd_mapping([sbs], [], catalog)
    assert results[0].status == "pending_review"
    assert "examples:" not in results[0].reason.lower()
