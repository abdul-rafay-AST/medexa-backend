"""Clinical speaker-role attribution for ambient mono-microphone sessions.

Groq Whisper does not provide acoustic diarization. In outpatient PT visits,
speakers alternate and clinical language strongly signals role. This module
scores each utterance as therapist vs patient and applies turn-taking continuity
when lexical confidence is low — paired with voice clustering on each natural
speech-boundary upload from the browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SpeakerRole = Literal["therapist", "patient"]

_THERAPIST_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(let'?s|we'?ll|we will|i'?m going to|go ahead and|try to|please try)\b",
        r"\b(therapeutic exercise|manual therapy|neuromuscular|mobilization|rom\b|range of motion)\b",
        r"\b(can you|how does that feel|any pain|tell me|show me|on a scale|flex|extend)\b",
        r"\b(i want you to|we'?re going to|next we|assess|palpate|treatment plan)\b",
        r"\b(therapist|doctor|physician|pt\b|physical therapist)\b",
    )
)

_PATIENT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(i feel|i have|my pain|it hurts|when i|i can'?t|i cannot|hurts when)\b",
        r"\b(my back|my knee|my shoulder|my neck|my hip|my ankle|my leg)\b",
        r"\b(pain is|aching|stiff|swollen|numbness|tingling|worse|better)\b",
        r"\b(for about|two weeks|three days|since|yesterday|this morning)\b",
        r"\b(yes|no|okay|ok|uh huh|mm hmm)\b",
    )
)

_QUESTION_RE = re.compile(r"\?\s*$")


@dataclass(frozen=True)
class SpeakerClassification:
    role: SpeakerRole
    confidence: float
    therapist_score: float
    patient_score: float


def format_labeled_utterance(role: SpeakerRole, text: str) -> str:
    label = "Therapist" if role == "therapist" else "Patient"
    clean = text.strip()
    if clean.lower().startswith((f"{label.lower()}:", "therapist:", "patient:")):
        return clean
    return f"{label}: {clean}"


class SpeakerRoleClassifier:
    """Rule-based therapist/patient classifier with conversational continuity."""

    def __init__(self, *, low_confidence_threshold: float = 0.15) -> None:
        self._low_threshold = low_confidence_threshold

    def classify(
        self,
        text: str,
        *,
        last_speaker: SpeakerRole | None = None,
    ) -> SpeakerClassification:
        clean = text.strip()
        if not clean:
            role: SpeakerRole = last_speaker or "patient"
            return SpeakerClassification(
                role=role,
                confidence=0.3,
                therapist_score=0.0,
                patient_score=0.0,
            )

        t_score = self._score(clean, _THERAPIST_PATTERNS)
        p_score = self._score(clean, _PATIENT_PATTERNS)

        if _QUESTION_RE.search(clean):
            t_score += 1.5

        first_person_symptom = bool(
            re.search(r"\b(i feel|my pain|it hurts|when i)\b", clean, re.IGNORECASE)
        )
        if first_person_symptom:
            p_score += 2.0

        imperative = bool(
            re.search(r"^(let'?s|try|go ahead|now |next )", clean, re.IGNORECASE)
        )
        if imperative:
            t_score += 1.5

        margin = abs(t_score - p_score)
        if margin < self._low_threshold:
            if last_speaker is None:
                role = "patient"
            else:
                role = "patient" if last_speaker == "therapist" else "therapist"
            confidence = 0.45 + min(0.2, margin)
        elif t_score > p_score:
            role = "therapist"
            confidence = min(0.98, 0.55 + margin * 0.12)
        else:
            role = "patient"
            confidence = min(0.98, 0.55 + margin * 0.12)

        return SpeakerClassification(
            role=role,
            confidence=round(confidence, 3),
            therapist_score=t_score,
            patient_score=p_score,
        )

    @staticmethod
    def _score(text: str, patterns: tuple[re.Pattern[str], ...]) -> float:
        total = 0.0
        for pattern in patterns:
            if pattern.search(text):
                total += 1.0
        return total
