"""ICD-10-AM explicit diagnosis + symptom-inference matcher (SA Path A).

Ported from BillingEngine / NewLookupBundle symptom matcher with optional
candidate_codes filtering for live keyword-index performance.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Optional, Set


AUTO_DETECT_STATUSES = frozenset(
    {
        "stated_or_confirmed_diagnosis",
        "direct_symptom_code",
        "direct_observed_sign_candidate",
    }
)

REVIEW_STATUSES = frozenset(
    {
        "diagnostic_candidate_not_confirmed",
        "candidate_requires_objective_confirmation",
        "urgent_candidate_requires_objective_confirmation",
        "family_candidate_exact_subtype_not_supported",
    }
)


def normalize(value: str) -> str:
    value = (
        unicodedata.normalize("NFKC", value)
        .replace("\u2019", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9%]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [normalize(x) for x in parts if normalize(x)]


def contains(text: str, phrase: str) -> bool:
    p = normalize(phrase)
    return bool(p and p in text)


def any_present(text: str, phrases: list[str]) -> bool:
    return any(contains(text, p) for p in phrases)


def group_hit(text: str, group: list[str]) -> tuple[bool, list[str]]:
    hits = [p for p in group if contains(text, p)]
    return bool(hits), hits


def token_positions(text: str, phrase: str) -> list[int]:
    toks = text.split()
    pt = normalize(phrase).split()
    if not pt:
        return []
    out: list[int] = []
    for i in range(len(toks) - len(pt) + 1):
        if toks[i : i + len(pt)] == pt:
            out.append(i)
    return out


def groups_close(text: str, groups: list[list[str]], max_gap: int = 6) -> bool:
    if len(groups) < 2:
        return True
    pos: list[list[int]] = []
    for g in groups[:2]:
        gp: list[int] = []
        for term in g:
            gp.extend(token_positions(text, term))
        if not gp:
            return False
        pos.append(gp)
    return min(abs(a - b) for a in pos[0] for b in pos[1]) <= max_gap


def map_hit_to_confidence(hit: dict[str, Any]) -> tuple[str, int, bool]:
    """Return (transcript_support, confidence_score, auto_detect)."""
    status = str(hit.get("status") or "")
    match_type = str(hit.get("match_type") or "")
    raw = int(hit.get("score") or 0)

    if match_type == "explicit_diagnosis" or status == "stated_or_confirmed_diagnosis":
        return "supported", min(100, max(90, raw if raw <= 110 else 100)), True

    if status in {"direct_symptom_code", "direct_observed_sign_candidate"}:
        # Map raw ~70-100 into 80-95 so live gate (>=80) accepts direct hits.
        mapped = min(95, max(80, 70 + max(0, raw - 70)))
        return "supported", mapped, True

    if status in REVIEW_STATUSES or status:
        mapped = min(75, max(50, 45 + max(0, raw // 4)))
        return "weak", mapped, False

    return "weak", 40, False


def match_icd_symptoms(
    lookup: dict[str, Any],
    transcript: str,
    *,
    top: int = 20,
    candidate_codes: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    """Match ICD codes; optionally restrict to candidate_codes from keyword index."""
    sents = sentences(transcript)
    windows: list[tuple[int, str]] = []
    for i, s in enumerate(sents):
        windows.append((i, s))
        if i + 1 < len(sents):
            windows.append((i, s + " " + sents[i + 1]))

    code_filter: Optional[Set[str]] = None
    if candidate_codes is not None:
        code_filter = {c for c in candidate_codes if c and c != "_meta"}

    results: list[dict[str, Any]] = []

    for code, entry in lookup.items():
        if code == "_meta":
            continue
        if code_filter is not None and code not in code_filter:
            continue
        if not isinstance(entry, dict):
            continue

        best: dict[str, Any] | None = None
        neg = entry.get("negation_context", []) or []
        fam = entry.get("family_history_context", []) or []
        unc = entry.get("uncertainty_context", []) or []
        description = str(entry.get("description") or entry.get("label") or code)

        for idx, w in windows:
            explicit = [
                p
                for p in entry.get(
                    "explicit_diagnosis_trigger_phrases",
                    entry.get("trigger_phrases", []),
                )
                or []
                if contains(w, p)
            ]
            if not explicit:
                continue
            if any_present(w, list(neg) + list(fam) + list(unc)):
                continue
            score = 100 + max(len(normalize(p).split()) for p in explicit)
            cand = {
                "code": code,
                "description": description,
                "match_type": "explicit_diagnosis",
                "status": "stated_or_confirmed_diagnosis",
                "score": score,
                "evidence": explicit[:3],
                "sentence_index": idx,
                "fallback_only": bool(entry.get("fallback_only", False)),
            }
            if best is None or cand["score"] > best["score"]:
                best = cand

        inf = entry.get("symptom_inference") or {}
        if inf.get("enabled"):
            for idx, w in windows:
                if any_present(
                    w,
                    entry.get("symptom_exclude_if_present", list(neg) + list(fam)) or [],
                ):
                    continue
                anchors = [
                    p
                    for p in entry.get("symptom_trigger_phrases", []) or []
                    if contains(w, p)
                ]
                groups = inf.get("required_symptom_groups", []) or []
                hits: list[str] = []
                hit_count = 0
                for g in groups:
                    ok, gh = group_hit(w, g or [])
                    if ok:
                        hit_count += 1
                        hits.extend(gh[:2])
                minimum = inf.get("minimum_evidence_groups", len(groups) or 1)
                if not anchors and hit_count < minimum:
                    continue
                if (
                    inf.get("mode") in {"direct_symptom_code", "direct_observed_sign"}
                    and not anchors
                ):
                    if not groups_close(w, groups, 6):
                        continue
                mandatory = inf.get("mandatory_qualifier_groups", []) or []
                mandatory_hits: list[str] = []
                if mandatory:
                    all_mandatory = True
                    for g in mandatory:
                        ok, gh = group_hit(w, g or [])
                        if not ok:
                            all_mandatory = False
                            break
                        mandatory_hits.extend(gh[:2])
                    if (
                        not all_mandatory
                        and inf.get("mode") == "symptom_pattern_with_explicit_qualifier"
                    ):
                        exact_qualifier_supported = False
                    else:
                        exact_qualifier_supported = True
                else:
                    exact_qualifier_supported = True

                objective = inf.get("objective_confirmation_context", []) or []
                objective_present = any_present(w, objective) if objective else False
                mode = inf.get("mode")
                status = inf.get("output_status", "diagnostic_candidate_not_confirmed")
                if mode == "objective_confirmation_required" and not objective_present:
                    status = "candidate_requires_objective_confirmation"
                elif (
                    mode == "symptom_pattern_with_explicit_qualifier"
                    and not exact_qualifier_supported
                ):
                    status = "family_candidate_exact_subtype_not_supported"

                mode_score = {
                    "direct_symptom_code": 70,
                    "direct_observed_sign": 65,
                    "symptom_supported_candidate": 55,
                    "symptom_fallback_candidate": 50,
                    "symptom_pattern_with_explicit_qualifier": 45,
                    "objective_confirmation_required": 40,
                }.get(mode, 30)
                score = (
                    mode_score
                    + hit_count * 8
                    + (12 if anchors else 0)
                    + (8 if objective_present else 0)
                )
                if entry.get("fallback_only"):
                    score -= 5
                cand = {
                    "code": code,
                    "description": description,
                    "match_type": "symptom_pattern",
                    "status": status,
                    "score": score,
                    "evidence": list(
                        dict.fromkeys(anchors[:2] + hits + mandatory_hits)
                    )[:10],
                    "evidence_groups_matched": hit_count,
                    "evidence_groups_required": minimum,
                    "sentence_index": idx,
                    "fallback_only": bool(entry.get("fallback_only", False)),
                }
                if best is None or cand["score"] > best["score"]:
                    best = cand
        if best:
            results.append(best)

    results.sort(key=lambda x: (-x["score"], x["fallback_only"], x["code"]))
    return results[:top]
