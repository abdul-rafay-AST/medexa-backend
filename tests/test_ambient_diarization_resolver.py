from __future__ import annotations

from medexa.core.ambient_diarization_resolver import AmbientDiarizationResolver
from medexa.core.ambient_speaker_diarizer import AmbientSpeakerDiarizer
from medexa.core.deepgram_speaker_mapper import DeepgramSpeakerRoleMapper
from medexa.core.speaker_role_classifier import SpeakerRoleClassifier
from medexa.schemas import SessionState
from medexa.services.transcription import TranscriptionResult, TranscriptSegment


def test_resolver_uses_voice_for_single_speaker_deepgram_chunk() -> None:
    classifier = SpeakerRoleClassifier()
    resolver = AmbientDiarizationResolver(
        voice_diarizer=AmbientSpeakerDiarizer(classifier),
        deepgram_mapper=DeepgramSpeakerRoleMapper(classifier),
    )
    state = SessionState(session_id="sess-voice")
    state.last_ambient_speaker = "therapist"

    first = resolver.resolve(
        audio=b"\x00" * 2000,
        content_type="audio/webm",
        transcript="It hurts when I bend my knee.",
        transcription=TranscriptionResult(
            transcript="It hurts when I bend my knee.",
            segments=[
                TranscriptSegment(start=0.0, end=1.0, text="It hurts when I bend my knee.", speaker_id=0),
            ],
            provider="deepgram",
            diarization_method="deepgram",
        ),
        state=state,
        client_pitch_hz=None,
        chunk_start_ts=0.0,
        chunk_end_ts=5.0,
    )
    assert first.method in {"hybrid", "voice", "text"}
    assert first.primary_role == "patient"


def test_resolver_uses_deepgram_when_two_speakers_in_one_chunk() -> None:
    classifier = SpeakerRoleClassifier()
    resolver = AmbientDiarizationResolver(
        voice_diarizer=AmbientSpeakerDiarizer(classifier),
        deepgram_mapper=DeepgramSpeakerRoleMapper(classifier),
    )
    state = SessionState(session_id="sess-multi")

    result = resolver.resolve(
        audio=b"\x00" * 2000,
        content_type="audio/webm",
        transcript="Can you flex your knee? It hurts when I bend it.",
        transcription=TranscriptionResult(
            transcript="Can you flex your knee? It hurts when I bend it.",
            segments=[
                TranscriptSegment(start=0.0, end=1.0, text="Can you flex your knee?", speaker_id=0),
                TranscriptSegment(start=1.1, end=2.5, text="It hurts when I bend it.", speaker_id=1),
            ],
            provider="deepgram",
            diarization_method="deepgram",
        ),
        state=state,
        client_pitch_hz=None,
        chunk_start_ts=0.0,
        chunk_end_ts=5.0,
    )
    assert result.method == "deepgram"
    assert len(result.utterances) == 2
    speakers = {utterance.speaker for utterance in result.utterances}
    assert speakers == {"therapist", "patient"}
