from datetime import timedelta
from pathlib import Path

from medexa.core.suggestion_generator import SuggestionGenerator
from medexa.loaders.cpt_metadata_loader import CptMetadataLoader
from medexa.schemas import DetectedEntity
from medexa.utils.time import now_utc

gen = SuggestionGenerator(
    CptMetadataLoader(Path("config/cpt_metadata.json")), cooldown_seconds=120
)


def _entity(cpt: str = "97140", region: str | None = "shoulder_right") -> DetectedEntity:
    return DetectedEntity(
        activity_label="manual_therapy",
        matched_phrase="soft tissue work",
        body_region=region,
        is_billable=True,
        possible_cpt=cpt,
        source_chunk_id="c1",
    )


def test_billable_entity_creates_suggestion():
    out = gen.generate("s1", [_entity()], existing=[], now=now_utc())
    assert len(out) == 1
    assert out[0].cpt_code == "97140"
    assert out[0].suggestion_type == "cpt_apply"


def test_non_billable_entity_skipped():
    e = _entity()
    e.is_billable = False
    assert gen.generate("s1", [e], existing=[], now=now_utc()) == []


def test_dedupe_within_same_batch():
    out = gen.generate("s1", [_entity(), _entity()], existing=[], now=now_utc())
    assert len(out) == 1


def test_dedupe_against_existing_within_cooldown():
    now = now_utc()
    first = gen.generate("s1", [_entity()], existing=[], now=now)
    second = gen.generate("s1", [_entity()], existing=first, now=now + timedelta(seconds=10))
    assert second == []


def test_resuggest_after_cooldown():
    now = now_utc()
    first = gen.generate("s1", [_entity()], existing=[], now=now)
    later = gen.generate("s1", [_entity()], existing=first, now=now + timedelta(seconds=200))
    assert len(later) == 1


def test_applied_suggestion_blocks_resuggest():
    now = now_utc()
    first = gen.generate("s1", [_entity()], existing=[], now=now)
    first[0].status = "applied"
    later = gen.generate("s1", [_entity()], existing=first, now=now + timedelta(seconds=999))
    assert later == []
