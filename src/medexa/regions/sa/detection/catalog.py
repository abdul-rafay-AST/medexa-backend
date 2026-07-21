"""Load SA SBS / ICD-10-AM lookup catalogs and keyword indexes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from medexa.regions.bundle import RegionBundle

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "if",
    "in",
    "into",
    "is",
    "it",
    "no",
    "not",
    "of",
    "on",
    "or",
    "such",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "they",
    "this",
    "to",
    "was",
    "will",
    "with",
    "has",
    "have",
    "had",
    "been",
    "patient",
    "pt",
    "client",
    "diagnosis",
    "diagnosed",
    "history",
    "hx",
    "due",
    "other",
    "unspecified",
    "disease",
    "syndrome",
    "disorder",
    "type",
}

_WORD_RE = re.compile(r"\b[a-z0-9]+\b")


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as fh:
        return json.load(fh)


def _load_lookup_dict(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k != "_meta" and isinstance(v, dict)}


def _index_phrases(lookup: dict[str, dict]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for code, entry in lookup.items():
        phrases = list(entry.get("trigger_phrases") or [])
        label = entry.get("label")
        if label:
            phrases.append(str(label))
        for phrase in phrases:
            for word in _WORD_RE.findall(str(phrase).lower()):
                if len(word) > 2 and word not in _STOP_WORDS:
                    index.setdefault(word, set()).add(code)
    too_common = [w for w, codes in index.items() if len(codes) > 200]
    for word in too_common:
        del index[word]
    return index


def _index_icd_phrases(lookup: dict[str, dict]) -> dict[str, set[str]]:
    """Index ICD entries using all symptom-inference fields."""
    index: dict[str, set[str]] = {}
    for code, entry in lookup.items():
        phrases: list[str] = []
        for key in (
            "explicit_diagnosis_trigger_phrases",
            "trigger_phrases",
            "symptom_trigger_phrases",
        ):
            val = entry.get(key)
            if isinstance(val, list):
                phrases.extend(str(p) for p in val if p)
        for key in ("label", "description"):
            val = entry.get(key)
            if val:
                phrases.append(str(val))
        inf = entry.get("symptom_inference") or {}
        for group_key in ("required_symptom_groups", "mandatory_qualifier_groups"):
            for group in inf.get(group_key) or []:
                if isinstance(group, list):
                    phrases.extend(str(p) for p in group if p)
        for phrase in phrases:
            for word in _WORD_RE.findall(str(phrase).lower()):
                if len(word) > 2 and word not in _STOP_WORDS:
                    index.setdefault(word, set()).add(code)
    too_common = [w for w, codes in index.items() if len(codes) > 200]
    for word in too_common:
        del index[word]
    return index


def _load_snomed_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = _load_json(path)
    rows = raw if isinstance(raw, list) else []
    labels: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("SBS Code hyphenated")
        desc = row.get("Long description")
        if code and desc:
            labels[str(code)] = str(desc)
    return labels


def _load_icd_descriptions(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = _load_json(path)
    descriptions: dict[str, str] = {}

    def _walk(nodes: list[Any]) -> None:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            code = node.get("code")
            desc = node.get("description")
            if code and desc:
                descriptions[str(code)] = str(desc)
            _walk(node.get("sub_codes") or [])

    if isinstance(raw, list):
        _walk(raw)
    return descriptions


def _load_unique_icd_descriptions(path: Path) -> dict[str, str]:
    """Flat Unique-ICD10 list; preferred display labels when present."""
    if not path.exists():
        return {}
    raw = _load_json(path)
    rows = raw if isinstance(raw, list) else raw.get("codes", []) if isinstance(raw, dict) else []
    if not isinstance(rows, list):
        return {}
    descriptions: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("code") or row.get("Code")
        desc = row.get("description") or row.get("Description")
        if code and desc:
            descriptions[str(code)] = str(desc)
    return descriptions


def _load_sbs_icd_mapping(path: Path) -> dict[str, set[str]]:
    """Parse SBS–ICD mapping; supports Direct_ICD10_Codes object lists."""
    if not path.exists():
        return {}
    raw = _load_json(path)
    rows = raw.get("mappings", []) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return {}
    mapping: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sbs = row.get("sbs_code") or row.get("SBS_Code") or row.get("SBS Code hyphenated")
        if not sbs:
            continue
        codes: set[str] = set()
        direct = row.get("Direct_ICD10_Codes") or row.get("ICD10_Codes") or []
        if isinstance(direct, list):
            for item in direct:
                if isinstance(item, dict) and item.get("code"):
                    codes.add(str(item["code"]))
                elif isinstance(item, str) and item.strip():
                    codes.add(item.strip())
        mapping[str(sbs)] = codes
    return mapping


@dataclass
class SaBillingCatalog:
    """In-memory SA billing assets for file-based Path A detection."""

    sbs_lookup: dict[str, dict] = field(default_factory=dict)
    icd_lookup: dict[str, dict] = field(default_factory=dict)
    sbs_labels: dict[str, str] = field(default_factory=dict)
    icd_descriptions: dict[str, str] = field(default_factory=dict)
    sbs_icd_mapping: dict[str, set[str]] = field(default_factory=dict)
    sbs_keyword_index: dict[str, set[str]] = field(default_factory=dict)
    icd_keyword_index: dict[str, set[str]] = field(default_factory=dict)

    def sbs_display_name(self, code: str) -> str:
        entry = self.sbs_lookup.get(code) or {}
        return (
            str(entry.get("label") or "")
            or self.sbs_labels.get(code)
            or code
        )

    def icd_display_name(self, code: str) -> str:
        entry = self.icd_lookup.get(code) or {}
        return (
            self.icd_descriptions.get(code)
            or str(entry.get("label") or entry.get("description") or "")
            or code
        )


def load_sa_catalog(bundle: RegionBundle) -> SaBillingCatalog:
    paths = bundle.asset_paths
    sbs_path = paths.resolve("codes/medexa_sbs_lookup.json")
    icd_path = paths.resolve("codes/medexa_icd10_lookup.json")
    snomed_path = paths.resolve("codes/sbs_v3_snomed.json")
    icd_am_path = paths.resolve("codes/icd10_am_ksa.json")
    unique_icd_path = paths.resolve("codes/unique_icd10_codes.json")
    mapping_path = paths.resolve("rules/sbs_icd10_mapping.json")

    sbs_lookup = _load_lookup_dict(sbs_path)
    icd_lookup = _load_lookup_dict(icd_path)
    # Unique labels override AM descriptions when present (BillingEngine parity).
    icd_descriptions = _load_icd_descriptions(icd_am_path)
    icd_descriptions.update(_load_unique_icd_descriptions(unique_icd_path))
    return SaBillingCatalog(
        sbs_lookup=sbs_lookup,
        icd_lookup=icd_lookup,
        sbs_labels=_load_snomed_labels(snomed_path),
        icd_descriptions=icd_descriptions,
        sbs_icd_mapping=_load_sbs_icd_mapping(mapping_path),
        sbs_keyword_index=_index_phrases(sbs_lookup),
        icd_keyword_index=_index_icd_phrases(icd_lookup),
    )
