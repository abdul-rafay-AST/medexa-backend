"""Reject common Whisper silent-chunk hallucinations (e.g. repeated "Thank you")."""

from __future__ import annotations

import re
from typing import Any

_HALLUCINATION_RE = re.compile(
    r"^(?:"
    r"thank(?:s| you)(?:\s+for\s+watching)?|"
    r"thanks(?:\s+for\s+watching)?|"
    r"please\s+subscribe|"
    r"subtitle(?:s)?\s+by|"
    r"that'?s\s+all|"
    r"bye|"
    r"you"
    r")\.?\s*$",
    re.IGNORECASE,
)


def is_likely_whisper_hallucination(text: str) -> bool:
    clean = re.sub(r"\s+", " ", text.strip())
    if not clean:
        return True
    normalized = clean.lower().rstrip(".")
    if normalized.count("thank you") >= 2 or normalized.count("thanks") >= 2:
        return True
    return bool(_HALLUCINATION_RE.match(clean))


def should_reject_whisper_segment(segment: dict[str, Any]) -> bool:
    text = str(segment.get("text", "")).strip()
    if is_likely_whisper_hallucination(text):
        return True

    no_speech = float(segment.get("no_speech_prob") or 0)
    avg_logprob = float(segment.get("avg_logprob") or 0)
    start = float(segment.get("start") or 0)
    end = float(segment.get("end") or start)
    duration = max(0.0, end - start)
    word_count = len(text.split())

    if no_speech >= 0.55 and word_count <= 4:
        return True
    if avg_logprob < -1.05 and word_count <= 3 and duration < 4.0:
        return True
    return False


def filter_whisper_transcript(text: str, segments: list[dict[str, Any]] | None = None) -> str:
    if segments:
        kept = [
            str(segment.get("text", "")).strip()
            for segment in segments
            if str(segment.get("text", "")).strip() and not should_reject_whisper_segment(segment)
        ]
        merged = " ".join(kept).strip()
        if merged and not is_likely_whisper_hallucination(merged):
            return merged
        return ""

    if is_likely_whisper_hallucination(text):
        return ""
    return text.strip()
