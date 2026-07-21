"""Stemmed subsequence phrase matcher for SA Medexa lookup entries (no LLM)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

_WORD_BOUNDARY_PHRASES = {
    "tens",
    "mfr",
    "fce",
    "at eval",
    "at evaluation",
    "massage",
    "group session",
    "lsvt",
    "nmes",
    "lllt",
    "iastm",
    "ther ex",
    "ther act",
}

_GENERIC_ACTION_VERBS = {
    "do",
    "perform",
    "work",
    "complete",
    "finish",
    "start",
    "begin",
    "continue",
    "apply",
    "place",
    "transition",
    "initiate",
    "deliver",
    "provide",
    "conduct",
    "give",
    "use",
    "administer",
    "execute",
    "put",
    "run",
    "spend",
    "practice",
}

_IRREGULAR_VERBS = {
    "did": "do",
    "does": "do",
    "done": "do",
    "doing": "do",
    "began": "begin",
    "begun": "begin",
    "went": "go",
    "gone": "go",
    "got": "get",
    "gotten": "get",
    "put": "put",
    "putting": "put",
    "ran": "run",
    "running": "run",
    "spent": "spend",
    "spending": "spend",
}

_WORD_RE = re.compile(r"[a-z0-9']+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_STEM_CANONICAL = {"exercis": "exercise"}


def stem(word: str) -> str:
    w = word.lower()
    if len(w) <= 3:
        return w
    suffixes = [
        ("ization", "ize"),
        ("isation", "ise"),
        ("ational", "ate"),
        ("tional", "tion"),
        ("ies", "y"),
        ("ing", ""),
        ("edly", ""),
        ("edness", ""),
        ("ed", ""),
        ("ization", ""),
        ("es", ""),
        ("s", ""),
    ]
    for suf, repl in suffixes:
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            return w[: -len(suf)] + repl
    return w


def normalize_word(word: str) -> str:
    base = stem(word)
    base = _IRREGULAR_VERBS.get(word.lower(), base)
    return _STEM_CANONICAL.get(base, base)


def _trigger_is_ambiguous(trigger: str) -> bool:
    trigger_norm = trigger.lower().strip()
    tokens = tokenize(trigger_norm)
    if len(tokens) == 1 and (len(tokens[0]) <= 4 or trigger_norm in _WORD_BOUNDARY_PHRASES):
        return True
    return trigger_norm in _WORD_BOUNDARY_PHRASES


def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("\u2019", "'")
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"(?m)^\s*[a-z][a-z0-9 ]{0,25}:\s*", "", text)
    return text


def split_sentences(text: str) -> List[str]:
    text = normalize_text(text)
    text = re.sub(r"\n+", ". ", text)
    parts = _SENT_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def tokenize(sentence: str) -> List[str]:
    return _WORD_RE.findall(sentence)


@dataclass
class TokenIndex:
    tokens: List[str]
    stems: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.stems:
            self.stems = [normalize_word(t) for t in self.tokens]


def build_index(sentence: str) -> TokenIndex:
    return TokenIndex(tokens=tokenize(sentence))


def find_phrase_span(idx: TokenIndex, phrase: str, max_gap: int = 2):
    span = _find_phrase_span_ordered(idx, phrase, max_gap=max_gap)
    if span is not None:
        return span
    return _find_phrase_span_unordered(idx, phrase, max_gap=max_gap)


def _find_phrase_span_ordered(idx: TokenIndex, phrase: str, max_gap: int = 2):
    phrase_words = [normalize_word(w) for w in tokenize(phrase)]
    if not phrase_words:
        return None
    n = len(idx.stems)
    for start in range(n):
        if idx.stems[start] != phrase_words[0]:
            continue
        cursor = start
        matched_to = start
        ok = True
        for pw in phrase_words[1:]:
            found_at = None
            for j in range(cursor + 1, min(cursor + 2 + max_gap, n)):
                if idx.stems[j] == pw:
                    found_at = j
                    break
            if found_at is None:
                ok = False
                break
            cursor = found_at
            matched_to = found_at
        if ok:
            return (start, matched_to)
    return None


def _find_phrase_span_unordered(idx: TokenIndex, phrase: str, max_gap: int = 2):
    phrase_words = [normalize_word(w) for w in tokenize(phrase)]
    if len(phrase_words) < 2:
        return None
    n = len(idx.stems)
    window = len(phrase_words) + max_gap * len(phrase_words)
    needed = set(phrase_words)
    for start in range(n):
        end = min(start + window, n)
        window_stems = idx.stems[start:end]
        if needed.issubset(set(window_stems)):
            positions = []
            for w in needed:
                for k in range(start, end):
                    if idx.stems[k] == w:
                        positions.append(k)
                        break
            if positions and len(positions) == len(needed):
                return (min(positions), max(positions))
    return None


def phrase_present_anywhere(idx: TokenIndex, phrase: str, max_gap: int = 2) -> bool:
    return find_phrase_span(idx, phrase, max_gap=max_gap) is not None


def context_within_distance(
    idx: TokenIndex, context_phrase: str, span, max_token_distance: int, max_gap: int = 1
) -> bool:
    ctx_span = find_phrase_span(idx, context_phrase, max_gap=max_gap)
    if ctx_span is None:
        return False
    c_start, c_end = ctx_span
    t_start, t_end = span
    if c_end < t_start:
        distance = t_start - c_end
    elif c_start > t_end:
        distance = c_start - t_end
    else:
        distance = 0
    return distance <= max_token_distance


@dataclass
class LookupMatch:
    trigger_phrase: str
    matched_text: str
    sentence: str
    sentence_index: int
    context_word: Optional[str]
    excluded: bool = False
    exclusion_phrase: Optional[str] = None


class MedexaLookupMatcher:
    def __init__(
        self,
        proximity_tokens: int = 10,
        phrase_gap: int = 2,
        use_generic_action_fallback: bool = True,
    ):
        self.proximity_tokens = proximity_tokens
        self.phrase_gap = phrase_gap
        self.use_generic_action_fallback = use_generic_action_fallback

    def match_entry(self, entry: dict, transcript: str) -> list[LookupMatch]:
        triggers = entry.get("trigger_phrases") or []
        if not triggers:
            return []

        required = entry.get("required_context") or []
        exclude_phrases = entry.get("exclude_if_present") or []
        sentences = split_sentences(transcript)
        results: list[LookupMatch] = []
        seen: set[tuple[int, str]] = set()

        for s_i, sentence in enumerate(sentences):
            idx = build_index(sentence)
            if not idx.tokens:
                continue

            for trigger in triggers:
                span = find_phrase_span(idx, trigger, max_gap=self.phrase_gap)
                if span is None:
                    continue

                exclusion_phrase = None
                for ex_phrase in exclude_phrases:
                    if phrase_present_anywhere(idx, ex_phrase, max_gap=self.phrase_gap):
                        exclusion_phrase = ex_phrase
                        break

                context_word_found = None
                if required and not exclusion_phrase:
                    for ctx in required:
                        if context_within_distance(
                            idx, ctx, span, self.proximity_tokens, max_gap=1
                        ):
                            context_word_found = ctx
                            break
                    if context_word_found is None and self.use_generic_action_fallback:
                        if not _trigger_is_ambiguous(trigger):
                            t_start, t_end = span
                            lo = max(0, t_start - self.proximity_tokens)
                            hi = min(len(idx.stems), t_end + 1 + self.proximity_tokens)
                            for k in range(lo, hi):
                                if idx.stems[k] in _GENERIC_ACTION_VERBS:
                                    context_word_found = idx.tokens[k] + " (generic)"
                                    break
                    if required and context_word_found is None:
                        continue

                key = (s_i, trigger)
                if key in seen:
                    continue
                seen.add(key)

                t_start, t_end = span
                matched_text = " ".join(idx.tokens[t_start : t_end + 1])
                results.append(
                    LookupMatch(
                        trigger_phrase=trigger,
                        matched_text=matched_text,
                        sentence=sentence,
                        sentence_index=s_i,
                        context_word=context_word_found,
                        excluded=exclusion_phrase is not None,
                        exclusion_phrase=exclusion_phrase,
                    )
                )
                break

        return results
