import json
from pathlib import Path
from typing import TypedDict

class NcciRule(TypedDict):
    cpt_a: str
    cpt_b: str
    payable_code: str
    bundled_code: str
    conflict_type: str
    body_region_sensitive: bool
    modifier_59_possible: bool
    explanation: str

class NcciRulesLoader:
    def __init__(self, config_path: Path):
        self._rules: dict[tuple[str, str], NcciRule] = {}
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        with open(config_path, encoding="utf-8") as f:
            data: list[NcciRule] = json.load(f)
            for rule in data:
                # Skip non-rule entries such as metadata/comment objects
                # (e.g. {"_sources": ...}, {"_review_needed": []}).
                if not (isinstance(rule, dict) and "cpt_a" in rule and "cpt_b" in rule):
                    continue
                pair1 = (rule["cpt_a"], rule["cpt_b"])
                pair2 = (rule["cpt_b"], rule["cpt_a"])
                self._rules[pair1] = rule
                self._rules[pair2] = rule

    def check_conflict(self, cpt_a: str, cpt_b: str) -> NcciRule | None:
        return self._rules.get((cpt_a, cpt_b))
