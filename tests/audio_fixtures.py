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
    return _pcm_to_wav(samples, sample_rate)


def make_voice_like_wav_bytes(
    fundamental_hz: float,
    *,
    duration_seconds: float = 3.0,
    sample_rate: int = 16_000,
) -> bytes:
    """Speech-like harmonic stack for realistic pitch/timbre separation tests."""
    sample_count = int(sample_rate * duration_seconds)
    times = np.linspace(0.0, duration_seconds, sample_count, endpoint=False)
    signal = (
        0.45 * np.sin(2.0 * np.pi * fundamental_hz * times)
        + 0.22 * np.sin(2.0 * np.pi * 2.0 * fundamental_hz * times)
        + 0.12 * np.sin(2.0 * np.pi * 3.0 * fundamental_hz * times)
        + 0.06 * np.sin(2.0 * np.pi * 4.0 * fundamental_hz * times)
    )
    envelope = 0.65 + 0.35 * np.sin(2.0 * np.pi * 3.0 * times)
    samples = (signal * envelope).astype(np.float32)
    rng = np.random.default_rng(int(fundamental_hz))
    samples += rng.normal(0.0, 0.015, size=sample_count).astype(np.float32)
    return _pcm_to_wav(samples, sample_rate)


def _pcm_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buffer.getvalue()
