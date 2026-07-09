from __future__ import annotations

import logging
from typing import Any

from medexa.adapters.groq.client import GroqClient, GroqClientError
from medexa.services.transcription import (
    TranscriptionResult,
    TranscriptionUnavailable,
)

logger = logging.getLogger(__name__)

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
        if not audio:
            raise TranscriptionUnavailable("Empty audio payload")

        ctype = (content_type or "audio/webm").split(";")[0].strip().lower()
        ext = _EXTENSION_MAP.get(ctype, "webm")
        filename = f"chunk.{ext}"

        try:
            text = self._client.transcribe_audio(
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

        return TranscriptionResult(transcript=text, segments=[])
