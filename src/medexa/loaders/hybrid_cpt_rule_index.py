from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class CptPhraseRule:
    """Value object: one phrase → CPT mapping with optional context gates."""

    phrase: str
    cpt_code: str
    activity_label: str | None
    required_context: frozenset[str]
    exclude_if_present: frozenset[str]
    source: Literal["legacy_flat", "legacy_synonym", "medexa_lookup"]
    context_window_tokens: int = 10


@dataclass(frozen=True)
class CptPhraseMatch:
    phrase: str
    cpt_code: str
    activity_label: str | None
    start_index: int


class HybridCptRuleIndex:
    """Hybrid index: legacy config phrases + MEDEXA CPT FILES context-aware rules.

    Specification pattern: each rule carries its own match policy (required context,
  exclude phrases). Longest-phrase-first matching reduces partial overlap false positives.
    """

    def __init__(self, config_dir: Path, cpt_files_dir: Path) -> None:
        self._rules: list[CptPhraseRule] = []
        self._phrase_to_label: dict[str, str] = {}
        self._build(config_dir, cpt_files_dir)
        self._rules.sort(key=lambda r: len(r.phrase), reverse=True)

    def _build(self, config_dir: Path, cpt_files_dir: Path) -> None:
        self._load_synonyms(config_dir / "activity_synonyms.json")
        self._load_legacy_flat(config_dir / "cpt_lookup.json")
        lookup_path = cpt_files_dir / "LOOKUPS" / "medexa_cpt_lookup.json"
        if lookup_path.exists():
            self._load_medexa_lookup(lookup_path)

    @staticmethod
    def _is_meta_key(key: str) -> bool:
        return key.startswith("_")

    def _load_synonyms(self, path: Path) -> None:
        data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        for phrase, label in data.items():
            if self._is_meta_key(phrase):
                continue
            self._phrase_to_label[phrase.lower()] = label

    def _load_legacy_flat(self, path: Path) -> None:
        data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
        for phrase, cpt in data.items():
            if self._is_meta_key(phrase):
                continue
            key = phrase.lower()
            self._rules.append(
                CptPhraseRule(
                    phrase=key,
                    cpt_code=cpt,
                    activity_label=self._phrase_to_label.get(key),
                    required_context=frozenset(),
                    exclude_if_present=frozenset(),
                    source="legacy_flat",
                )
            )

    def _load_medexa_lookup(self, path: Path) -> None:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        for cpt_code, record in data.items():
            if self._is_meta_key(cpt_code) or not isinstance(record, dict):
                continue
            required = frozenset(x.lower() for x in record.get("required_context", []))
            exclude = frozenset(x.lower() for x in record.get("exclude_if_present", []))
            label = record.get("label")
            for phrase in record.get("trigger_phrases", []):
                key = phrase.lower()
                self._rules.append(
                    CptPhraseRule(
                        phrase=key,
                        cpt_code=cpt_code,
                        activity_label=label,
                        required_context=required,
                        exclude_if_present=exclude,
                        source="medexa_lookup",
                    )
                )

    def match(self, text_lower: str) -> list[CptPhraseMatch]:
        if not text_lower.strip():
            return []
        tokens = re.findall(r"[a-z0-9']+", text_lower)
        sentences = [s.strip() for s in re.split(r"[.!?]+", text_lower) if s.strip()]
        seen: set[tuple[str, str]] = set()
        matches: list[CptPhraseMatch] = []

        for rule in self._rules:
            start = text_lower.find(rule.phrase)
            if start < 0:
                continue
            if not self._passes_context(rule, text_lower, tokens, start):
                continue
            if not self._passes_exclude(rule, sentences, start):
                continue
            key = (rule.phrase, rule.cpt_code)
            if key in seen:
                continue
            seen.add(key)
            activity = rule.activity_label or self._phrase_to_label.get(rule.phrase)
            matches.append(
                CptPhraseMatch(
                    phrase=rule.phrase,
                    cpt_code=rule.cpt_code,
                    activity_label=activity,
                    start_index=start,
                )
            )
        return matches

    @staticmethod
    def _passes_context(rule: CptPhraseRule, text: str, tokens: list[str], start: int) -> bool:
        if not rule.required_context:
            return True
        prefix = text[:start]
        token_index = len(re.findall(r"[a-z0-9']+", prefix))
        window_start = max(0, token_index - rule.context_window_tokens)
        window_end = min(len(tokens), token_index + rule.context_window_tokens + len(rule.phrase.split()))
        window = " ".join(tokens[window_start:window_end])
        return any(ctx in window for ctx in rule.required_context)

    @staticmethod
    def _passes_exclude(rule: CptPhraseRule, sentences: list[str], start: int) -> bool:
        if not rule.exclude_if_present:
            return True
        for sentence in sentences:
            if rule.phrase in sentence:
                return not any(ex in sentence for ex in rule.exclude_if_present)
        return True

    def get_activity_label(self, phrase: str) -> str | None:
        return self._phrase_to_label.get(phrase.lower())
