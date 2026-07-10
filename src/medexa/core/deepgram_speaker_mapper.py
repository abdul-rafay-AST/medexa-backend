"""Map Deepgram numeric speaker IDs to clinical therapist/patient roles."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from medexa.core.speaker_role_classifier import SpeakerRole, SpeakerRoleClassifier
from medexa.schemas import SessionState
from medexa.services.transcription import TranscriptSegment

DiarizationMethod = Literal["deepgram", "voice", "text", "hybrid"]


@dataclass(frozen=True)
class DeepgramDiarizationResult:
    role: SpeakerRole
    confidence: float
    method: DiarizationMethod
    segments: list[TranscriptSegment]
    dominant_speaker_id: int | None = None


class DeepgramSpeakerRoleMapper:
    """Session-stable mapping from Deepgram speaker indices to clinical roles.

    Deepgram separates *who spoke* (acoustic diarization). This layer resolves
    *which role* each speaker plays (therapist vs patient) using locked session
    state plus lexical clinical cues on first encounter — the same enrollment
    pattern used in production medical scribes.
    """

    def __init__(self, text_classifier: SpeakerRoleClassifier) -> None:
        self._text_classifier = text_classifier

    def resolve(
        self,
        *,
        segments: list[TranscriptSegment],
        full_transcript: str,
        state: SessionState,
    ) -> DeepgramDiarizationResult:
        roles_map = state.ambient_deepgram_speaker_roles
        speaker_texts = _group_text_by_speaker(segments)

        for speaker_id, texts in speaker_texts.items():
            key = str(speaker_id)
            if key in roles_map:
                continue
            combined = " ".join(texts).strip() or full_transcript
            classification = self._text_classifier.classify(
                combined,
                last_speaker=state.last_ambient_speaker,
            )
            roles_map[key] = classification.role

        _reconcile_two_party_roles(roles_map)

        resolved_segments: list[TranscriptSegment] = []
        speaker_word_counts: dict[int, int] = defaultdict(int)
        for segment in segments:
            role: SpeakerRole | None = None
            if segment.speaker_id is not None:
                role = roles_map.get(str(segment.speaker_id))
                speaker_word_counts[segment.speaker_id] += len(segment.text.split())
            resolved_segments.append(segment.model_copy(update={"speaker_role": role}))

        dominant_speaker_id = _dominant_speaker_id(speaker_word_counts, segments)
        if dominant_speaker_id is not None:
            dominant_role = roles_map[str(dominant_speaker_id)]
            confidence = 0.93
        else:
            classification = self._text_classifier.classify(
                full_transcript,
                last_speaker=state.last_ambient_speaker,
            )
            dominant_role = classification.role
            confidence = max(classification.confidence, 0.55)

        return DeepgramDiarizationResult(
            role=dominant_role,
            confidence=confidence,
            method="deepgram",
            segments=resolved_segments,
            dominant_speaker_id=dominant_speaker_id,
        )


def _group_text_by_speaker(segments: list[TranscriptSegment]) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    for segment in segments:
        if segment.speaker_id is None or not segment.text.strip():
            continue
        grouped[segment.speaker_id].append(segment.text.strip())
    return grouped


def _dominant_speaker_id(
    word_counts: dict[int, int],
    segments: list[TranscriptSegment],
) -> int | None:
    if word_counts:
        return max(word_counts.items(), key=lambda item: item[1])[0]
    for segment in segments:
        if segment.speaker_id is not None:
            return segment.speaker_id
    return None


def _reconcile_two_party_roles(
    roles_map: dict[str, SpeakerRole],
) -> None:
    """When two speakers are enrolled, ensure they map to opposite clinical roles."""
    if len(roles_map) < 2:
        return
    keys = sorted(roles_map.keys(), key=lambda key: int(key) if key.isdigit() else key)
    first_role = roles_map[keys[0]]
    for key in keys[1:]:
        if roles_map[key] == first_role:
            roles_map[key] = "patient" if first_role == "therapist" else "therapist"
