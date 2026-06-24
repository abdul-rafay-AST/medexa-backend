import json
from pathlib import Path

import pytest

from medexa.core.ncci_conflict_checker import NcciConflictChecker
from medexa.loaders.ncci_rules_loader import NcciRulesLoader

# Self-contained fixture data so tests don't depend on the live config files.
_RULES = [
    {
        "cpt_a": "97110",
        "cpt_b": "97140",
        "conflict_type": "mutually_exclusive",
        "body_region_sensitive": True,
        "modifier_59_possible": True,
        "explanation": "Region-sensitive pair.",
    },
    {
        "cpt_a": "97112",
        "cpt_b": "97116",
        "conflict_type": "mutually_exclusive",
        "body_region_sensitive": False,
        "modifier_59_possible": True,
        "explanation": "Non-region-sensitive pair.",
    },
]


@pytest.fixture
def checker(tmp_path: Path) -> NcciConflictChecker:
    rules_file = tmp_path / "ncci_rules.json"
    rules_file.write_text(json.dumps(_RULES))
    return NcciConflictChecker(NcciRulesLoader(rules_file))


def test_region_sensitive_same_region_conflicts(checker: NcciConflictChecker):
    alerts = checker.check_conflicts(
        "s1", [("97110", "shoulder_right"), ("97140", "shoulder_right")]
    )
    assert len(alerts) == 1
    assert alerts[0].body_region == "shoulder_right"


def test_region_sensitive_different_region_no_conflict_bug_b(checker: NcciConflictChecker):
    # Same pair on DIFFERENT regions must NOT conflict (this was the bug).
    alerts = checker.check_conflicts(
        "s1", [("97110", "shoulder_right"), ("97140", "knee_left")]
    )
    assert alerts == []


def test_non_region_sensitive_always_conflicts(checker: NcciConflictChecker):
    alerts = checker.check_conflicts(
        "s1", [("97112", "knee_left"), ("97116", "spine_lumbar")]
    )
    assert len(alerts) == 1


def test_no_conflict_for_unrelated_pair(checker: NcciConflictChecker):
    alerts = checker.check_conflicts(
        "s1", [("97110", "shoulder_right"), ("97116", "shoulder_right")]
    )
    assert alerts == []
