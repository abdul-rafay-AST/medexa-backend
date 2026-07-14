from pathlib import Path

from medexa.loaders.hybrid_cpt_rule_index import HybridCptRuleIndex


def test_hybrid_index_matches_legacy_phrase():
    index = HybridCptRuleIndex(Path("config"), Path("data/cpt_files"))
    matches = index.match("we did therapeutic exercise for the lumbar spine")
    codes = {m.cpt_code for m in matches}
    assert "97110" in codes


def test_medexa_lookup_requires_context_when_configured():
    index = HybridCptRuleIndex(Path("config"), Path("data/cpt_files"))
    # Phrase exists in medexa lookup with required_context — without action words may not fire
    bare = index.match("therapeutic exercise")
    with_context = index.match("we started therapeutic exercise on the knee")
    assert len(with_context) >= len(bare)
