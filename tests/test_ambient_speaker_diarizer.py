from medexa.core.ambient_speaker_diarizer import AmbientSpeakerDiarizer
from medexa.core.speaker_role_classifier import SpeakerRoleClassifier
from medexa.schemas import SessionState
from tests.audio_fixtures import make_sine_wav_bytes


def _state() -> SessionState:
    return SessionState(session_id="sess-voice-test")


def test_voice_clusters_map_to_patient_and_therapist_roles():
    diarizer = AmbientSpeakerDiarizer(SpeakerRoleClassifier())
    state = _state()

    therapist_audio = make_sine_wav_bytes(130.0)
    patient_audio = make_sine_wav_bytes(240.0)

    therapist = diarizer.classify(
        audio=therapist_audio,
        content_type="audio/wav",
        transcript="Let's start therapeutic exercise for lumbar ROM.",
        state=state,
    )
    patient = diarizer.classify(
        audio=patient_audio,
        content_type="audio/wav",
        transcript="My lower back hurts when I bend forward.",
        state=state,
    )

    assert therapist.role == "therapist"
    assert patient.role == "patient"
    assert therapist.voice_cluster != patient.voice_cluster
    assert therapist.method in {"voice", "hybrid"}
    assert patient.method in {"voice", "hybrid"}


def test_second_chunk_from_same_voice_keeps_cluster():
    diarizer = AmbientSpeakerDiarizer(SpeakerRoleClassifier())
    state = _state()
    audio = make_sine_wav_bytes(150.0)

    first = diarizer.classify(
        audio=audio,
        content_type="audio/wav",
        transcript="Can you try flexing your knee?",
        state=state,
    )
    second = diarizer.classify(
        audio=make_sine_wav_bytes(152.0),
        content_type="audio/wav",
        transcript="How does that feel?",
        state=state,
    )

    assert first.voice_cluster == second.voice_cluster
    assert second.role == "therapist"
