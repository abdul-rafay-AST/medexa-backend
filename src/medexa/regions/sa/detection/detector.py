"""Confidence scoring and SA file-based SBS/ICD detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from medexa.regions.bundle import RegionBundle
from medexa.regions.sa.detection.catalog import SaBillingCatalog, load_sa_catalog
from medexa.regions.sa.detection.icd_symptom_matcher import (
    map_hit_to_confidence,
    match_icd_symptoms,
)
from medexa.regions.sa.detection.lookup_matcher import LookupMatch, MedexaLookupMatcher

CONFIDENCE_THRESHOLD = 80
_WORD_RE = re.compile(r"\b[a-z0-9]+\b")


def compute_transcript_confidence(
    support: str,
    supporting_sentence_count: int,
    matched_phrases: list[str],
    matched_context: list[str],
) -> int | None:
    if support == "supported":
        base = 75 + 5 * len(matched_phrases) + 3 * len(matched_context)
        extra = max(0, supporting_sentence_count - 1) * 5
        return min(100, base + extra)
    if support == "weak":
        return 20
    if support == "suppressed":
        return 0
    return None


def _aggregate_entry_matches(
    matches: list[LookupMatch],
) -> tuple[str, list[str], list[str], str | None, str]:
    if not matches:
        return (
            "weak",
            [],
            [],
            None,
            "No supporting clinical phrases found in transcript.",
        )

    supporting = [m for m in matches if not m.excluded]
    excluded = [m for m in matches if m.excluded]

    if supporting:
        phrases = list(dict.fromkeys(m.trigger_phrase for m in supporting))
        contexts = list(
            dict.fromkeys(m.context_word for m in supporting if m.context_word)
        )
        sentence_count = len({m.sentence_index for m in supporting})
        return (
            "supported",
            phrases,
            contexts,
            None,
            f"Transcript language supports this code ({sentence_count} sentence(s)).",
        )

    if excluded:
        ex = excluded[0]
        return (
            "suppressed",
            [ex.trigger_phrase],
            [],
            ex.exclusion_phrase,
            f"Phrase matched but suppressed by exclusion '{ex.exclusion_phrase}'.",
        )

    return (
        "weak",
        [],
        [],
        None,
        "No supporting clinical phrases found in transcript.",
    )


@dataclass(frozen=True)
class DetectedSaCode:
    code: str
    label: str
    kind: str  # "sbs" | "icd10_am"
    confidence: int
    matched_phrases: list[str] = field(default_factory=list)
    matched_context: list[str] = field(default_factory=list)
    guidance: str = ""
    matched_text: str = ""
    review_only: bool = False


@dataclass
class DetectedSaCodes:
    sbs_codes: list[DetectedSaCode] = field(default_factory=list)
    icd10_am_codes: list[DetectedSaCode] = field(default_factory=list)
    icd10_am_review: list[DetectedSaCode] = field(default_factory=list)


class SaFileDetector:
    """Detect SBS and ICD-10-AM codes from transcript using SA flatfiles only."""

    def __init__(
        self,
        catalog: SaBillingCatalog,
        *,
        confidence_threshold: int = CONFIDENCE_THRESHOLD,
    ) -> None:
        self._catalog = catalog
        self._threshold = confidence_threshold
        self._matcher = MedexaLookupMatcher()

    @classmethod
    def from_bundle(
        cls,
        bundle: RegionBundle,
        *,
        confidence_threshold: int = CONFIDENCE_THRESHOLD,
    ) -> SaFileDetector:
        return cls(load_sa_catalog(bundle), confidence_threshold=confidence_threshold)

    @property
    def catalog(self) -> SaBillingCatalog:
        return self._catalog

    def detect_from_transcript(self, text: str) -> DetectedSaCodes:
        if not text or not text.strip():
            return DetectedSaCodes()

        words = set(_WORD_RE.findall(text.lower()))
        sbs_candidates: set[str] = set()
        icd_candidates: set[str] = set()
        for word in words:
            sbs_candidates.update(self._catalog.sbs_keyword_index.get(word, set()))
            icd_candidates.update(self._catalog.icd_keyword_index.get(word, set()))

        sbs_hits: list[DetectedSaCode] = []
        for code in sorted(sbs_candidates):
            entry = self._catalog.sbs_lookup.get(code)
            if not entry:
                continue
            hit = self._evaluate_code(code, entry, text, kind="sbs")
            if hit is not None:
                sbs_hits.append(hit)

        icd_auto: list[DetectedSaCode] = []
        icd_review: list[DetectedSaCode] = []
        if icd_candidates:
            raw_hits = match_icd_symptoms(
                self._catalog.icd_lookup, text, candidate_codes=icd_candidates
            )
            for hit in raw_hits:
                _support, confidence, auto_detect = map_hit_to_confidence(hit)
                code = hit["code"]
                description = str(
                    hit.get("description") or self._catalog.icd_display_name(code)
                )
                evidence = hit.get("evidence", [])
                matched_text = evidence[0] if evidence else code
                sa_code = DetectedSaCode(
                    code=code,
                    label=description,
                    kind="icd10_am",
                    confidence=confidence,
                    matched_phrases=evidence[:3],
                    matched_context=[],
                    guidance=(
                        f"Matched: {', '.join(evidence[:3])}." if evidence else ""
                    ),
                    matched_text=str(matched_text),
                    review_only=not auto_detect,
                )
                if auto_detect and confidence >= self._threshold:
                    icd_auto.append(sa_code)
                elif not auto_detect and confidence >= 50:
                    icd_review.append(sa_code)

        return DetectedSaCodes(
            sbs_codes=sbs_hits,
            icd10_am_codes=icd_auto,
            icd10_am_review=icd_review,
        )

    def _evaluate_code(
        self,
        code: str,
        entry: dict,
        transcript: str,
        *,
        kind: str,
    ) -> DetectedSaCode | None:
        matches = self._matcher.match_entry(entry, transcript)
        support, phrases, contexts, _suppressed, guidance = _aggregate_entry_matches(matches)
        sentence_count = (
            len({m.sentence_index for m in matches if not m.excluded}) if matches else 0
        )
        confidence = compute_transcript_confidence(
            support, sentence_count, phrases, contexts
        )
        if confidence is None or confidence < self._threshold:
            return None

        matched_text = ""
        for m in matches:
            if not m.excluded:
                matched_text = m.matched_text or m.trigger_phrase
                break

        if kind == "sbs":
            label = self._catalog.sbs_display_name(code)
        else:
            label = self._catalog.icd_display_name(code)

        return DetectedSaCode(
            code=code,
            label=label,
            kind=kind,
            confidence=confidence,
            matched_phrases=phrases,
            matched_context=contexts,
            guidance=guidance,
            matched_text=matched_text or (phrases[0] if phrases else code),
        )
