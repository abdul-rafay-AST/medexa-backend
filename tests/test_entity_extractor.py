from pathlib import Path

from medexa.core.entity_extractor import EntityExtractor
from medexa.loaders.activity_synonym_loader import ActivitySynonymLoader
from medexa.loaders.body_region_normalizer import BodyRegionNormalizer
from medexa.loaders.cpt_lookup_loader import CptLookupLoader

extractor = EntityExtractor(
    ActivitySynonymLoader(Path("config/activity_synonyms.json")),
    BodyRegionNormalizer(Path("config/body_regions.json")),
    CptLookupLoader(Path("config/cpt_lookup.json")),
)


def test_activity_maps_to_cpt_and_is_billable_bug_c():
    entities = extractor.extract("We did some soft tissue work on the right shoulder", "c1")
    assert len(entities) == 1
    e=entities[0]
    assert e.activity_label == "manual_therapy"
    assert e.possible_cpt == "97140"
    assert e.body_region == "shoulder_right"
    assert e.is_billable is True


def test_negated_activity_is_not_billable():
    entities = extractor.extract("We did not do any massage today", "c2")
    assert len(entities) == 1
    assert entities[0].is_negated is True
    assert entities[0].is_billable is False


def test_stop_is_not_clinical_negation():
    # "stop" is a voice command, not clinical negation -> activity stays billable.
    entities = extractor.extract("stop, we just finished the massage", "c3")
    assert len(entities) == 1
    assert entities[0].is_negated is False
    assert entities[0].is_billable is True
