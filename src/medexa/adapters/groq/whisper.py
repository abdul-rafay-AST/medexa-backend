from __future__ import annotations

import logging
from typing import Any

from medexa.adapters.groq.client import GroqClient, GroqClientError
from medexa.core.whisper_hallucination_filter import filter_whisper_transcript
from medexa.services.transcription import (
    TranscriptionResult,
    TranscriptionUnavailable,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

MIN_WHISPER_BYTES = 1000

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


class GroqWhisperTranscriptionProvider:
    """Groq-hosted Whisper STT — OpenAI-compatible /audio/transcriptions."""

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str = "whisper-large-v3-turbo",
        base_url: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key, "timeout_seconds": 90.0}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = GroqClient(**kwargs)
        self._model_id = model_id

    def transcribe(self, audio: bytes, content_type: str | None = None) -> TranscriptionResult:
        if not audio or len(audio) < MIN_WHISPER_BYTES:
            raise TranscriptionUnavailable(
                "Audio chunk too short for transcription — speak a little longer."
            )

        ctype = (content_type or "audio/webm").split(";")[0].strip().lower()
        ext = _EXTENSION_MAP.get(ctype, "webm")
        filename = f"chunk.{ext}"

        try:
            payload = self._client.transcribe_audio(
                audio=audio,
                filename=filename,
                content_type=ctype,
                model=self._model_id,
                language="en",
            )
        except GroqClientError as exc:
            logger.warning("groq_whisper_failed", exc_info=True)
            raise TranscriptionUnavailable(str(exc)) from exc
        except Exception as exc:
            logger.warning("groq_whisper_failed", exc_info=True)
            raise TranscriptionUnavailable(f"Whisper transcription failed: {exc}") from exc

        raw_segments = payload.get("segments") if isinstance(payload.get("segments"), list) else []
        filtered = filter_whisper_transcript(str(payload.get("text", "")), raw_segments)
        if not filtered:
            logger.debug("groq_whisper_hallucination_filtered", extra={"extra_fields": {"raw": payload.get("text", "")}})
            return TranscriptionResult(transcript="", segments=[])

        segments = [
            TranscriptSegment(
                start=float(segment.get("start") or 0),
                end=float(segment.get("end") or 0),
                text=str(segment.get("text", "")).strip(),
            )
            for segment in raw_segments
            if str(segment.get("text", "")).strip()
        ]
        return TranscriptionResult(transcript=filtered, segments=segments)
