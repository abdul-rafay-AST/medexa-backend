"""Lightweight mono-audio voice fingerprints for ambient speaker clustering."""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16_000
_EXTENSION_MAP = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
}


class AudioDecodeError(RuntimeError):
    """Raised when ambient audio cannot be decoded for voice fingerprinting."""


@dataclass(frozen=True)
class PcmAudio:
    samples: np.ndarray
    sample_rate: int


def decode_audio_bytes(audio: bytes, content_type: str | None = None) -> PcmAudio:
    if not audio:
        raise AudioDecodeError("empty audio")
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype in {"audio/wav", "audio/x-wav"} or audio[:4] == b"RIFF":
        return _decode_wav(audio)
    return _decode_via_ffmpeg(audio, ctype)


def estimate_audio_duration_seconds(audio: bytes, content_type: str | None = None) -> float:
    """Return decoded audio length in seconds for session clock alignment."""
    try:
        pcm = decode_audio_bytes(audio, content_type)
    except AudioDecodeError:
        # Rough fallback for compressed blobs when ffmpeg is unavailable.
        return max(len(audio) / 4800.0, 0.25)
    if pcm.sample_rate <= 0:
        return 0.25
    return max(len(pcm.samples) / pcm.sample_rate, 0.25)


def resolve_chunk_duration_seconds(
    audio: bytes,
    content_type: str | None,
    *,
    client_duration_seconds: float | None = None,
) -> float:
    """Pick a stable utterance duration from decoded audio and optional client hint."""
    decoded = estimate_audio_duration_seconds(audio, content_type)
    if client_duration_seconds is not None and client_duration_seconds > 0:
        return max(0.25, min(float(client_duration_seconds), decoded + 0.35, 120.0))
    return max(0.25, min(decoded, 120.0))


def transcode_to_wav_bytes(audio: bytes, content_type: str | None = None) -> tuple[bytes, str]:
    """Decode arbitrary browser audio to mono WAV for reliable STT upload."""
    pcm = decode_audio_bytes(audio, content_type)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(pcm.sample_rate)
        clipped = np.clip(pcm.samples, -1.0, 1.0)
        wf.writeframes((clipped * 32767.0).astype(np.int16).tobytes())
    return buffer.getvalue(), "audio/wav"


def extract_voice_fingerprint(audio: bytes, content_type: str | None = None) -> np.ndarray:
    pcm = decode_audio_bytes(audio, content_type)
    return fingerprint_from_pcm(pcm.samples, pcm.sample_rate)


def fingerprint_from_pcm(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    if sample_rate <= 0:
        raise AudioDecodeError("invalid sample rate")
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if len(x) < sample_rate // 5:
        raise AudioDecodeError("audio chunk too short for voice fingerprint")

    if sample_rate != TARGET_SAMPLE_RATE:
        x = _resample_linear(x, sample_rate, TARGET_SAMPLE_RATE)

    x = _trim_silence(x)
    if len(x) < TARGET_SAMPLE_RATE // 8:
        raise AudioDecodeError("not enough voiced audio")

    features = np.array(
        [
            float(np.sqrt(np.mean(x * x))) * 8.0,
            _zero_crossing_rate(x) * 8.0,
            _spectral_centroid(x, TARGET_SAMPLE_RATE) / (TARGET_SAMPLE_RATE / 2),
            _estimate_pitch(x, TARGET_SAMPLE_RATE) / (TARGET_SAMPLE_RATE / 2),
            *_normalized_band_shape(x, TARGET_SAMPLE_RATE, bands=8),
            *_mfcc_like(x, TARGET_SAMPLE_RATE, coeffs=8),
        ],
        dtype=np.float64,
    )
    norm = float(np.linalg.norm(features))
    if norm <= 1e-9:
        raise AudioDecodeError("degenerate voice fingerprint")
    return features / norm


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(1.0 - float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0)))


def _decode_wav(data: bytes) -> PcmAudio:
    with wave.open(io.BytesIO(data), "rb") as wf:
        sample_rate = wf.getframerate()
        sample_width = wf.getsampwidth()
        channels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())

    if sample_width == 2:
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
        scale = 32768.0
    elif sample_width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
        scale = 1.0
    else:
        raise AudioDecodeError(f"unsupported wav sample width: {sample_width}")

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    else:
        samples = samples / scale

    return PcmAudio(samples=samples.astype(np.float32), sample_rate=sample_rate)


def _decode_via_ffmpeg(data: bytes, content_type: str) -> PcmAudio:
    if not shutil.which("ffmpeg"):
        raise AudioDecodeError("ffmpeg is not installed")

    ext = _EXTENSION_MAP.get(content_type, "webm")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        input_path = tmp / f"chunk.{ext}"
        output_path = tmp / "decoded.wav"
        input_path.write_bytes(data)
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(input_path),
                "-ac",
                "1",
                "-ar",
                str(TARGET_SAMPLE_RATE),
                str(output_path),
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0 or not output_path.exists():
            stderr = proc.stderr.decode("utf-8", errors="replace")[:240]
            raise AudioDecodeError(f"ffmpeg decode failed: {stderr}")
        return _decode_wav(output_path.read_bytes())


def _resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return samples
    duration = len(samples) / src_rate
    target_len = max(1, int(duration * dst_rate))
    src_times = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    dst_times = np.linspace(0.0, duration, num=target_len, endpoint=False)
    return np.interp(dst_times, src_times, samples)


def _trim_silence(samples: np.ndarray, frame: int = 400, threshold: float = 0.012) -> np.ndarray:
    if len(samples) <= frame:
        return samples
    energies = np.array(
        [float(np.sqrt(np.mean(samples[i : i + frame] ** 2))) for i in range(0, len(samples) - frame, frame)]
    )
    voiced = np.where(energies >= threshold)[0]
    if voiced.size == 0:
        return samples
    start = int(voiced[0] * frame)
    end = min(len(samples), int((voiced[-1] + 1) * frame + frame))
    return samples[start:end]


def _zero_crossing_rate(samples: np.ndarray) -> float:
    if len(samples) < 2:
        return 0.0
    signs = np.sign(samples)
    return float(np.mean(signs[1:] != signs[:-1]))


def _estimate_pitch(samples: np.ndarray, sample_rate: int) -> float:
    frame = samples[: min(len(samples), sample_rate)]
    frame = frame - np.mean(frame)
    if np.max(np.abs(frame)) < 1e-5:
        return 0.0
    corr = np.correlate(frame, frame, mode="full")[len(frame) - 1 :]
    corr[: int(sample_rate / 500)] = 0
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


def _normalized_band_shape(samples: np.ndarray, sample_rate: int, *, bands: int) -> list[float]:
    energies = np.array(_spectral_band_energies(samples, sample_rate, bands=bands), dtype=np.float64)
    total = float(np.sum(energies))
    if total <= 1e-9:
        return [0.0] * bands
    return [float(value / total) for value in energies]


def _spectral_band_energies(samples: np.ndarray, sample_rate: int, *, bands: int) -> list[float]:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    if spectrum.size == 0:
        return [0.0] * bands
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
    max_freq = sample_rate / 2
    edges = np.linspace(0.0, max_freq, bands + 1)
    energies: list[float] = []
    for idx in range(bands):
        mask = (freqs >= edges[idx]) & (freqs < edges[idx + 1])
        energies.append(float(np.mean(spectrum[mask])) if np.any(mask) else 0.0)
    return energies


def _mfcc_like(samples: np.ndarray, sample_rate: int, *, coeffs: int) -> list[float]:
    frame_size = 512
    hop = 256
    frames: list[np.ndarray] = []
    for start in range(0, max(1, len(samples) - frame_size), hop):
        frame = samples[start : start + frame_size]
        if len(frame) < frame_size:
            frame = np.pad(frame, (0, frame_size - len(frame)))
        frames.append(np.abs(np.fft.rfft(frame * np.hanning(frame_size)))[: coeffs + 1])

    if not frames:
        return [0.0] * coeffs

    mel_means = np.mean(np.stack(frames, axis=0), axis=0)
    log_mel = np.log1p(mel_means[1 : coeffs + 1])
    return [float(v) for v in log_mel]
