from __future__ import annotations

import wave
import io

import numpy as np

from medexa.core.voice_fingerprint import (
    estimate_audio_duration_seconds,
    resolve_chunk_duration_seconds,
)


def _wav_bytes(duration_sec: float, sample_rate: int = 16_000) -> bytes:
    samples = np.zeros(int(duration_sec * sample_rate), dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.tobytes())
    return buf.getvalue()


def test_estimate_audio_duration_from_wav() -> None:
    audio = _wav_bytes(2.5)
    duration = estimate_audio_duration_seconds(audio, "audio/wav")
    assert 2.4 <= duration <= 2.6


def test_resolve_chunk_duration_prefers_client_hint_when_close() -> None:
    audio = _wav_bytes(3.0)
    duration = resolve_chunk_duration_seconds(audio, "audio/wav", client_duration_seconds=2.8)
    assert 2.7 <= duration <= 3.0
