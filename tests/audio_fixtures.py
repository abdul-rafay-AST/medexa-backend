"""Synthetic audio helpers for voice diarization tests."""

from __future__ import annotations

import io
import wave

import numpy as np


def make_sine_wav_bytes(
    frequency_hz: float,
    *,
    duration_seconds: float = 3.0,
    sample_rate: int = 16_000,
    amplitude: float = 0.35,
) -> bytes:
    sample_count = int(sample_rate * duration_seconds)
    times = np.linspace(0.0, duration_seconds, sample_count, endpoint=False)
    samples = (amplitude * np.sin(2.0 * np.pi * frequency_hz * times)).astype(np.float32)
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buffer.getvalue()
