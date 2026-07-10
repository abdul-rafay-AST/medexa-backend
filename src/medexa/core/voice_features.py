"""Voice feature extraction for ambient two-speaker diarization."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from medexa.core.voice_fingerprint import (
    AudioDecodeError,
    PcmAudio,
    TARGET_SAMPLE_RATE,
    cosine_distance,
    decode_audio_bytes,
    fingerprint_from_pcm,
)


@dataclass(frozen=True)
class VoiceFeatures:
  fingerprint: np.ndarray
  pitch_hz: float
  pitch_confidence: float
  spectral_centroid_hz: float
  voiced_ratio: float


def extract_voice_features(audio: bytes, content_type: str | None = None) -> VoiceFeatures:
    pcm = decode_audio_bytes(audio, content_type)
    return features_from_pcm(pcm.samples, pcm.sample_rate)


def features_from_pcm(samples: np.ndarray, sample_rate: int) -> VoiceFeatures:
    if sample_rate <= 0:
        raise AudioDecodeError("invalid sample rate")
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if len(x) < sample_rate // 5:
        raise AudioDecodeError("audio chunk too short")

    if sample_rate != TARGET_SAMPLE_RATE:
        from medexa.core.voice_fingerprint import _resample_linear

        x = _resample_linear(x, sample_rate, TARGET_SAMPLE_RATE)
        sample_rate = TARGET_SAMPLE_RATE

    from medexa.core.voice_fingerprint import _trim_silence

    voiced = _trim_silence(x)
    if len(voiced) < sample_rate // 8:
        raise AudioDecodeError("not enough voiced audio")

    pitch_hz, pitch_confidence = _estimate_pitch_multi(voiced, sample_rate)
    fingerprint = fingerprint_from_pcm(voiced, sample_rate)
    centroid = _spectral_centroid(voiced, sample_rate)
    voiced_ratio = float(len(voiced) / max(1, len(x)))

    return VoiceFeatures(
        fingerprint=fingerprint,
        pitch_hz=pitch_hz,
        pitch_confidence=pitch_confidence,
        spectral_centroid_hz=centroid,
        voiced_ratio=voiced_ratio,
    )


def blend_pitch(server_hz: float, server_conf: float, client_hz: float | None) -> tuple[float, float]:
    if client_hz is None or client_hz <= 0:
        return server_hz, server_conf
    if server_hz <= 0:
        return client_hz, 0.75
    if server_conf < 0.35:
        return client_hz, 0.8
    blended = 0.35 * server_hz + 0.65 * client_hz
    return blended, min(0.98, server_conf + 0.15)


def joint_voice_distance(
    left: VoiceFeatures,
    right: VoiceFeatures,
    *,
    left_pitch: float | None = None,
    right_pitch: float | None = None,
) -> float:
    fp_dist = cosine_distance(left.fingerprint, right.fingerprint)
    lp = left_pitch if left_pitch is not None else left.pitch_hz
    rp = right_pitch if right_pitch is not None else right.pitch_hz
    if lp > 0 and rp > 0:
        pitch_dist = min(1.0, abs(lp - rp) / 90.0)
    else:
        pitch_dist = 0.55
    centroid_dist = 0.0
    if left.spectral_centroid_hz > 0 and right.spectral_centroid_hz > 0:
        centroid_dist = min(
            1.0,
            abs(left.spectral_centroid_hz - right.spectral_centroid_hz) / 1200.0,
        )
    return 0.5 * fp_dist + 0.35 * pitch_dist + 0.15 * centroid_dist


def _estimate_pitch_multi(samples: np.ndarray, sample_rate: int) -> tuple[float, float]:
    frame = sample_rate // 8
    hop = frame // 2
    pitches: list[float] = []
    for start in range(0, max(1, len(samples) - frame), hop):
        chunk = samples[start : start + frame]
        pitch = _estimate_pitch_frame(chunk, sample_rate)
        if pitch > 0:
            pitches.append(pitch)
    if not pitches:
        return 0.0, 0.0
    median = float(np.median(pitches))
    spread = float(np.std(pitches))
    confidence = max(0.0, min(0.98, 0.9 - spread / max(median, 1.0)))
    return median, confidence


def _estimate_pitch_frame(samples: np.ndarray, sample_rate: int) -> float:
    frame = samples - np.mean(samples)
    if np.max(np.abs(frame)) < 1e-5:
        return 0.0
    corr = np.correlate(frame, frame, mode="full")[len(frame) - 1 :]
    min_lag = int(sample_rate / 400)
    max_lag = int(sample_rate / 70)
    corr[:min_lag] = 0
    if max_lag < len(corr):
        corr[max_lag:] = 0
    peak = int(np.argmax(corr))
    if peak <= 0:
        return 0.0
    return float(sample_rate / peak)


def _spectral_centroid(samples: np.ndarray, sample_rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
    total = float(np.sum(spectrum))
    if total <= 1e-9:
        return 0.0
    return float(np.sum(freqs * spectrum) / total)
