from pathlib import Path

from medexa.core.entity_extractor import EntityExtractor
from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.loaders.hybrid_cpt_rule_index import HybridCptRuleIndex

extractor = EntityExtractor(
    HybridCptRuleIndex(Path("config"), Path("data/cpt_files")),
    BodyRegionNormalizer(Path("config/body_regions.json")),
)


def test_activity_maps_to_cpt_and_is_billable_bug_c():
    entities = extractor.extract("We did some soft tissue work on the right shoulder", "c1")
    assert len(entities) == 1
    e = entities[0]
    assert e.possible_cpt == "97140"
    assert e.body_region == "shoulder_right"
    assert e.is_billable is True


def test_negated_activity_is_not_billable():
    entities = extractor.extract("We did not do any massage today", "c2")
    assert len(entities) > 0
    assert all(e.is_negated is True for e in entities)
    assert all(e.is_billable is False for e in entities)


def test_stop_is_not_clinical_negation():
    entities = extractor.extract("stop, we just finished the massage", "c3")
    assert len(entities) == 1
    assert entities[0].is_negated is False
    assert entities[0].is_billable is True
