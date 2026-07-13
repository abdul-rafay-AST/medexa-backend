"""Deepgram Nova-3 Medical transcription with native speaker diarization."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from medexa.adapters.deepgram.client import DeepgramClient, DeepgramClientError
from medexa.core.voice_fingerprint import AudioDecodeError, transcode_to_wav_bytes
from medexa.services.transcription import (
    TranscriptionResult,
    TranscriptionUnavailable,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

MIN_AUDIO_BYTES = 400

_CONTENT_TYPE_MAP = {
    "audio/webm": "audio/webm",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/mpeg": "audio/mpeg",
    "audio/mp3": "audio/mpeg",
    "audio/mp4": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/ogg": "audio/ogg",
    "audio/flac": "audio/flac",
}


class DeepgramNovaTranscriptionProvider:
    """Deepgram Nova-3 Medical STT with batch diarization (diarize_model=latest)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "nova-3-medical",
        diarize_model: str = "latest",
        base_url: str | None = None,
        language: str = "en-US",
    ) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = DeepgramClient(**kwargs)
        self._model = model
        self._diarize_model = diarize_model
        self._language = language

    def transcribe(self, audio: bytes, content_type: str | None = None) -> TranscriptionResult:
        if not audio or len(audio) < MIN_AUDIO_BYTES:
            raise TranscriptionUnavailable(
                "Audio chunk too short for transcription — speak a little longer."
            )

        ctype = (content_type or "audio/webm").split(";")[0].strip().lower()
        upload_audio = audio
        upload_ctype = _CONTENT_TYPE_MAP.get(ctype, ctype)
        try:
            upload_audio, upload_ctype = transcode_to_wav_bytes(audio, ctype)
        except AudioDecodeError as exc:
            logger.warning("deepgram_transcode_failed: %s", exc)
            raise TranscriptionUnavailable(
                "Could not decode microphone audio — speak a little longer and try again."
            ) from exc

        if len(upload_audio) < MIN_AUDIO_BYTES:
            raise TranscriptionUnavailable(
                "Audio chunk too short for transcription — speak a little longer."
            )

        try:
            payload = self._transcribe_with_fallback(
                audio=upload_audio,
                content_type=upload_ctype,
            )
        except DeepgramClientError as exc:
            logger.warning("deepgram_transcribe_failed", exc_info=True)
            raise TranscriptionUnavailable(str(exc)) from exc
        except Exception as exc:
            logger.warning("deepgram_transcribe_failed", exc_info=True)
            raise TranscriptionUnavailable(f"Deepgram transcription failed: {exc}") from exc

        return _parse_deepgram_payload(payload)

    def _transcribe_with_fallback(self, *, audio: bytes, content_type: str) -> dict[str, Any]:
        try:
            return self._client.transcribe_file(
                audio=audio,
                content_type=content_type,
                model=self._model,
                diarize_model=self._diarize_model,
                language=self._language,
            )
        except DeepgramClientError as exc:
            if "400" not in str(exc) or not self._diarize_model:
                raise
            logger.warning("deepgram_retry_without_diarization")
            return self._client.transcribe_file(
                audio=audio,
                content_type=content_type,
                model=self._model,
                diarize_model=None,
                language=self._language,
            )


def _parse_deepgram_payload(payload: dict[str, Any]) -> TranscriptionResult:
    results = payload.get("results")
    if not isinstance(results, dict):
        return TranscriptionResult(transcript="", segments=[], diarization_method="none")

    channels = results.get("channels")
    if not isinstance(channels, list) or not channels:
        return TranscriptionResult(transcript="", segments=[], diarization_method="none")

    alternatives = channels[0].get("alternatives") if isinstance(channels[0], dict) else None
    if not isinstance(alternatives, list) or not alternatives:
        return TranscriptionResult(transcript="", segments=[], diarization_method="none")

    primary = alternatives[0] if isinstance(alternatives[0], dict) else {}
    transcript = str(primary.get("transcript", "")).strip()
    if not transcript:
        return TranscriptionResult(transcript="", segments=[], diarization_method="none")

    utterances = results.get("utterances")
    segments = _segments_from_utterances(utterances)
    if not segments:
        segments = _segments_from_words(primary.get("words"))

    has_speakers = any(segment.speaker_id is not None for segment in segments)
    diarization_method = "deepgram" if has_speakers else "none"
    distinct = len({segment.speaker_id for segment in segments if segment.speaker_id is not None})
    logger.info(
        "deepgram_chunk_parsed",
        extra={
            "extra_fields": {
                "segment_count": len(segments),
                "distinct_speakers": distinct,
                "diarization_method": diarization_method,
            }
        },
    )

    return TranscriptionResult(
        transcript=transcript,
        segments=segments,
        provider="deepgram",
        diarization_method=diarization_method,
    )


def _segments_from_utterances(utterances: object) -> list[TranscriptSegment]:
    if not isinstance(utterances, list):
        return []
    segments: list[TranscriptSegment] = []
    for item in utterances:
        if not isinstance(item, dict):
            continue
        text = str(item.get("transcript", "")).strip()
        if not text:
            continue
        speaker_raw = item.get("speaker")
        speaker_id = int(speaker_raw) if speaker_raw is not None else None
        segments.append(
            TranscriptSegment(
                start=float(item.get("start") or 0),
                end=float(item.get("end") or 0),
                text=text,
                speaker_id=speaker_id,
            )
        )
    return segments


def _segments_from_words(words: object) -> list[TranscriptSegment]:
    if not isinstance(words, list) or not words:
        return []

    grouped: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
    for word in words:
        if not isinstance(word, dict):
            continue
        token = str(word.get("punctuated_word") or word.get("word") or "").strip()
        if not token:
            continue
        speaker_raw = word.get("speaker")
        speaker_id = int(speaker_raw) if speaker_raw is not None else None
        grouped[speaker_id].append(word)

    segments: list[TranscriptSegment] = []
    for speaker_id, speaker_words in grouped.items():
        text = " ".join(
            str(w.get("punctuated_word") or w.get("word") or "").strip() for w in speaker_words
        ).strip()
        if not text:
            continue
        start = float(speaker_words[0].get("start") or 0)
        end = float(speaker_words[-1].get("end") or start)
        segments.append(
            TranscriptSegment(
                start=start,
                end=end,
                text=text,
                speaker_id=speaker_id,
            )
        )
    segments.sort(key=lambda segment: segment.start)
    return segments
