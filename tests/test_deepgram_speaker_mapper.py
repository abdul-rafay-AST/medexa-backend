from __future__ import annotations

from medexa.core.deepgram_speaker_mapper import DeepgramSpeakerRoleMapper
from medexa.core.speaker_role_classifier import SpeakerRoleClassifier
from medexa.schemas import SessionState
from medexa.services.transcription import TranscriptSegment


def test_deepgram_mapper_locks_speaker_roles_across_chunks() -> None:
    mapper = DeepgramSpeakerRoleMapper(SpeakerRoleClassifier())
    state = SessionState(session_id="sess-1")

    first = mapper.resolve(
        segments=[
            TranscriptSegment(
                start=0.0,
                end=1.0,
                text="Can you try to flex your knee?",
                speaker_id=0,
            )
        ],
        full_transcript="Can you try to flex your knee?",
        state=state,
    )
    assert first.role == "therapist"
    assert first.method == "deepgram"
    assert state.ambient_deepgram_speaker_roles["0"] == "therapist"

    second = mapper.resolve(
        segments=[
            TranscriptSegment(
                start=0.0,
                end=1.5,
                text="It hurts when I bend it.",
                speaker_id=1,
            )
        ],
        full_transcript="It hurts when I bend it.",
        state=state,
    )
    assert second.role == "patient"
    assert state.ambient_deepgram_speaker_roles["1"] == "patient"


def test_deepgram_mapper_reuses_locked_role_for_known_speaker() -> None:
    mapper = DeepgramSpeakerRoleMapper(SpeakerRoleClassifier())
    state = SessionState(session_id="sess-2")
    state.ambient_deepgram_speaker_roles["0"] = "therapist"

    result = mapper.resolve(
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text="Okay.", speaker_id=0),
        ],
        full_transcript="Okay.",
        state=state,
    )
    assert result.role == "therapist"
    assert result.segments[0].speaker_role == "therapist"
