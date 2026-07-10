"""Manual voice diarization smoke test with synthetic patient/therapist audio."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from medexa.core.ambient_speaker_diarizer import AmbientSpeakerDiarizer
from medexa.core.speaker_role_classifier import SpeakerRoleClassifier
from medexa.schemas import SessionState
from tests.audio_fixtures import make_voice_like_wav_bytes


def main() -> None:
    diarizer = AmbientSpeakerDiarizer(SpeakerRoleClassifier())
    state = SessionState(session_id="voice-smoke")

    samples = [
        ("therapist", 118.0, "Let's start therapeutic exercise for lumbar ROM."),
        ("patient", 212.0, "My lower back hurts when I bend forward."),
        ("therapist", 122.0, "Can you try flexing your knee ten times?"),
        ("patient", 218.0, "It hurts a little on the right side."),
    ]

    for expected, frequency, transcript in samples:
        audio = make_voice_like_wav_bytes(frequency)
        result = diarizer.classify(
            audio=audio,
            content_type="audio/wav",
            transcript=transcript,
            state=state,
            client_pitch_hz=frequency,
        )
        ok = "OK" if result.role == expected else "MISMATCH"
        print(
            f"[{ok}] expected={expected} got={result.role} "
            f"cluster={result.voice_cluster} method={result.method} "
            f"confidence={result.confidence:.2f} text='{transcript[:48]}...'"
        )


if __name__ == "__main__":
    main()
