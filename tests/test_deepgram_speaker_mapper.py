from __future__ import annotations

from medexa.core.deepgram_speaker_mapper import DeepgramSpeakerRoleMapper
from medexa.core.speaker_role_classifier import SpeakerRoleClassifier
from medexa.services.transcription import TranscriptSegment


def test_deepgram_mapper_assigns_opposite_roles_within_chunk() -> None:
    mapper = DeepgramSpeakerRoleMapper(SpeakerRoleClassifier())

    result = mapper.resolve_within_chunk(
        segments=[
            TranscriptSegment(
                start=0.0,
                end=1.0,
                text="Can you try to flex your knee?",
                speaker_id=0,
            ),
            TranscriptSegment(
                start=1.1,
                end=2.5,
                text="It hurts when I bend it.",
                speaker_id=1,
            ),
        ],
        full_transcript="Can you try to flex your knee? It hurts when I bend it.",
        last_speaker=None,
    )
    roles = {segment.speaker_role for segment in result.segments}
    assert roles == {"therapist", "patient"}


def test_deepgram_mapper_does_not_reuse_speaker_zero_across_chunks() -> None:
    mapper = DeepgramSpeakerRoleMapper(SpeakerRoleClassifier())

    patient_chunk = mapper.resolve_within_chunk(
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text="It hurts when I bend it.", speaker_id=0),
        ],
        full_transcript="It hurts when I bend it.",
        last_speaker="therapist",
    )
    assert patient_chunk.role == "patient"

    therapist_chunk = mapper.resolve_within_chunk(
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text="Can you flex your knee?", speaker_id=0),
        ],
        full_transcript="Can you flex your knee?",
        last_speaker="patient",
    )
    assert therapist_chunk.role == "therapist"
