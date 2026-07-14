"""Transcription service — Strategy pattern with Unavailable and AWS Transcribe adapters.

Healthcare / ops notes:
  * Amazon Transcribe (standard) uploads audio to S3 with SSE-S3.
  * Jobs are short-lived; lifecycle policies expire ``transcribe/`` prefixes.
  * No PHI in job names (UUID only).
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable
import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker_id: int | None = None
    speaker_role: Literal["therapist", "patient"] | None = None


class TranscriptionResult(BaseModel):
    transcript: str
    segments: list[TranscriptSegment] = []
    provider: Literal["groq_whisper", "deepgram", "aws_transcribe"] | None = None
    diarization_method: Literal["deepgram", "aws_transcribe", "none"] | None = None
    dominant_speaker_role: Literal["therapist", "patient"] | None = None
    speaker_confidence: float = 0.0


class TranscriptionUnavailable(RuntimeError):
    """Raised when no speech-to-text backend is configured."""


@runtime_checkable
class TranscriptionProvider(Protocol):
    def transcribe(self, audio: bytes, content_type: str | None = None) -> TranscriptionResult: ...


class UnavailableTranscriptionProvider:
    def transcribe(self, audio: bytes, content_type: str | None = None) -> TranscriptionResult:
        raise TranscriptionUnavailable(
            "Server-side audio transcription is not configured. "
            "Use typed transcript chunks, or set "
            "MEDEXA_TRANSCRIPTION_PROVIDER=deepgram (or groq_whisper, aws_transcribe)."
        )


class AwsTranscribeProvider:
    """Facade around :class:`AwsTranscribeBatchProvider` (standard Amazon Transcribe)."""

    def __init__(
        self,
        region_name: str | None = None,
        s3_bucket: str | None = None,
        *,
        enable_speaker_labels: bool = True,
        max_speaker_labels: int = 2,
        poll_timeout_seconds: float = 120.0,
        language_code: str = "en-US",
    ) -> None:
        from medexa.adapters.aws.transcribe_batch import (  # noqa: PLC0415
            AwsTranscribeBatchProvider,
        )

        if not s3_bucket:
            self._impl: AwsTranscribeBatchProvider | None = None
            self._missing_bucket = True
            return

        self._missing_bucket = False
        self._impl = AwsTranscribeBatchProvider(
            region_name=region_name or "us-east-2",
            s3_bucket=s3_bucket,
            language_code=language_code,
            enable_speaker_labels=enable_speaker_labels,
            max_speaker_labels=max_speaker_labels,
            poll_timeout_seconds=poll_timeout_seconds,
        )

    def transcribe(
        self, audio: bytes, content_type: str | None = None
    ) -> TranscriptionResult:
        if self._missing_bucket or self._impl is None:
            raise TranscriptionUnavailable(
                "MEDEXA_TRANSCRIBE_S3_BUCKET (or MEDEXA_S3_BUCKET) is not configured. "
                "Set it to enable Amazon Transcribe."
            )
        return self._impl.transcribe(audio, content_type)


class FallbackTranscriptionProvider:
    """Try primary STT first; on ``TranscriptionUnavailable`` use secondary.

    Used on HF Space so Amazon Transcribe is preferred and Deepgram keeps ambient
    alive if Transcribe/S3 is denied from the Space IP.
    """

    def __init__(self, *, primary: TranscriptionProvider, fallback: TranscriptionProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def transcribe(self, audio: bytes, content_type: str | None = None) -> TranscriptionResult:
        try:
            return self._primary.transcribe(audio, content_type)
        except TranscriptionUnavailable as exc:
            logger.warning("stt_primary_unavailable_failover: %s", exc)
            return self._fallback.transcribe(audio, content_type)
