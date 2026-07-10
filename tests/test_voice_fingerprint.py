import numpy as np

from medexa.core.voice_fingerprint import cosine_distance, fingerprint_from_pcm
from tests.audio_fixtures import make_sine_wav_bytes


def _fingerprint_from_wav(wav_bytes: bytes) -> np.ndarray:
    import wave
    import io

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        sample_rate = wf.getframerate()
    return fingerprint_from_pcm(samples, sample_rate)


def test_different_voice_frequencies_are_separable():
    low = _fingerprint_from_wav(make_sine_wav_bytes(120.0))
    high = _fingerprint_from_wav(make_sine_wav_bytes(260.0))
    same = _fingerprint_from_wav(make_sine_wav_bytes(120.0, duration_seconds=2.5))

    assert cosine_distance(low, high) > 0.03
    assert cosine_distance(low, same) < 0.03


def test_wav_decode_round_trip():
    wav = make_sine_wav_bytes(180.0)
    from medexa.core.voice_fingerprint import extract_voice_fingerprint

    fingerprint = extract_voice_fingerprint(wav, "audio/wav")
    assert fingerprint.shape[0] >= 16
    assert np.isfinite(fingerprint).all()
