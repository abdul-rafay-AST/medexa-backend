from medexa.core.ambient_speaker_diarizer import AmbientSpeakerDiarizer, CLUSTER_A, CLUSTER_B
from medexa.core.speaker_role_classifier import SpeakerRoleClassifier
from medexa.schemas import SessionState
from tests.audio_fixtures import make_sine_wav_bytes, make_voice_like_wav_bytes


def _state() -> SessionState:
    return SessionState(session_id="sess-voice-test")


def test_voice_like_harmonics_separate_male_and_female_pitch():
    diarizer = AmbientSpeakerDiarizer(SpeakerRoleClassifier())
    state = _state()

    therapist = diarizer.classify(
        audio=make_voice_like_wav_bytes(118.0),
        content_type="audio/wav",
        transcript="Let's start therapeutic exercise for lumbar ROM.",
        state=state,
        client_pitch_hz=118.0,
    )
    patient = diarizer.classify(
        audio=make_voice_like_wav_bytes(212.0),
        content_type="audio/wav",
        transcript="My lower back hurts when I bend forward.",
        state=state,
        client_pitch_hz=212.0,
    )

    assert therapist.voice_cluster == CLUSTER_A
    assert patient.voice_cluster == CLUSTER_B
    assert therapist.role == "therapist"
    assert patient.role == "patient"
    assert therapist.method in {"voice", "hybrid"}
    assert patient.method in {"voice", "hybrid"}


def test_alternating_voices_stay_locked_after_enrollment():
    diarizer = AmbientSpeakerDiarizer(SpeakerRoleClassifier())
    state = _state()

    sequence = [
        (make_voice_like_wav_bytes(125.0), 125.0, "Can you raise your arm overhead?"),
        (make_voice_like_wav_bytes(220.0), 220.0, "It hurts when I lift it."),
        (make_voice_like_wav_bytes(127.0), 127.0, "Try external rotation with the band."),
        (make_voice_like_wav_bytes(215.0), 215.0, "Okay, that feels tight."),
    ]

    roles: list[str] = []
    clusters: list[str] = []
    for audio, pitch, text in sequence:
        result = diarizer.classify(
            audio=audio,
            content_type="audio/wav",
            transcript=text,
            state=state,
            client_pitch_hz=pitch,
        )
        roles.append(result.role)
        clusters.append(result.voice_cluster or "")

    assert clusters[0] == clusters[2] == CLUSTER_A
    assert clusters[1] == clusters[3] == CLUSTER_B
    assert roles[0] == roles[2] == "therapist"
    assert roles[1] == roles[3] == "patient"


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
