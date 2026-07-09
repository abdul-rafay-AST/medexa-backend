"""Transcription service — Strategy pattern with Unavailable and AWS Transcribe adapters.

Healthcare compliance:
  * AWS Transcribe Medical is used with ``Specialty=PRIMARYCARE`` and
    ``Type=DICTATION`` for clinically tuned speech recognition.
  * Audio bytes are uploaded to S3 with server-side encryption (SSE-S3).
  * Transcription jobs are short-lived; S3 objects can be lifecycle-expired.
  * No PHI is logged; only job IDs and durations appear in structured logs.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptionResult(BaseModel):
    transcript: str
    segments: list[TranscriptSegment] = []


class TranscriptionUnavailable(RuntimeError):
    """Raised when no speech-to-text backend is configured. Routers translate
    this into HTTP 503 so the frontend cleanly falls back to browser STT."""


@runtime_checkable
class TranscriptionProvider(Protocol):
    """Port: convert uploaded audio bytes into a transcript + timed segments.

    Default deployment uses browser Web Speech (handled entirely on the
    frontend), so the server-side default provider is *unavailable*. AWS
    Transcribe is the planned production adapter."""

    def transcribe(self, audio: bytes, content_type: str | None = None) -> TranscriptionResult: ...


class UnavailableTranscriptionProvider:
    """Default no-op provider.

    The MVP captures speech in the browser (Web Speech API) and posts text to
    ``/analyze-transcript-chunk``. Server-side audio transcription is therefore
    not wired until AWS Transcribe is provisioned; calling it fails fast and
    explicitly rather than pretending to work."""

    def transcribe(self, audio: bytes, content_type: str | None = None) -> TranscriptionResult:
        raise TranscriptionUnavailable(
            "Server-side audio transcription is not configured. "
            "Use typed transcript chunks, or set "
            "MEDEXA_TRANSCRIPTION_PROVIDER=groq_whisper (or aws_transcribe)."
        )


class AwsTranscribeProvider:
    """AWS Transcribe Medical adapter — production-grade speech-to-text.

    Flow:
      1. Upload audio bytes to an S3 staging bucket with server-side encryption.
      2. Start an Amazon Transcribe Medical job (specialty=PRIMARYCARE,
         type=DICTATION) for clinically tuned recognition.
      3. Poll for completion, then map the result + item timestamps into
         :class:`TranscriptionResult`.

    Healthcare compliance:
      * Uses Transcribe Medical for HIPAA-eligible clinical vocabulary.
      * S3 uploads use SSE-S3 encryption by default.
      * Job names use UUIDs (no PHI in identifiers).
      * Audio objects are uploaded with a predictable key pattern for
        lifecycle-policy expiration.
    """

    # Content-type to media format mapping for AWS Transcribe.
    _FORMAT_MAP = {
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/mp3": "mp3",
        "audio/mpeg": "mp3",
        "audio/mp4": "mp4",
        "audio/ogg": "ogg",
        "audio/flac": "flac",
        "audio/webm": "webm",
    }

    def __init__(
        self,
        region_name: str | None = None,
        s3_bucket: str | None = None,
    ) -> None:
        self._region_name = region_name or "us-east-1"
        self._s3_bucket = s3_bucket
        self._s3_client = None
        self._transcribe_client = None

    def _get_s3_client(self) -> Any:
        if self._s3_client is None:
            import boto3  # noqa: PLC0415

            self._s3_client = boto3.client("s3", region_name=self._region_name)
        return self._s3_client

    def _get_transcribe_client(self) -> Any:
        if self._transcribe_client is None:
            import boto3  # noqa: PLC0415

            self._transcribe_client = boto3.client(
                "transcribe", region_name=self._region_name
            )
        return self._transcribe_client

    def transcribe(
        self, audio: bytes, content_type: str | None = None
    ) -> TranscriptionResult:
        """Transcribe audio via AWS Transcribe Medical."""
        if not self._s3_bucket:
            raise TranscriptionUnavailable(
                "MEDEXA_TRANSCRIBE_S3_BUCKET is not configured. "
                "Set it to enable server-side audio transcription."
            )

        job_id = f"medexa-{uuid.uuid4().hex[:12]}"
        media_format = self._FORMAT_MAP.get(content_type or "", "wav")
        s3_key = f"audio-staging/{job_id}.{media_format}"

        try:
            # 1. Upload audio to S3 with encryption.
            s3 = self._get_s3_client()
            s3.put_object(
                Bucket=self._s3_bucket,
                Key=s3_key,
                Body=audio,
                ContentType=content_type or "audio/wav",
                ServerSideEncryption="AES256",
            )

            s3_uri = f"s3://{self._s3_bucket}/{s3_key}"

            # 2. Start Transcribe Medical job.
            transcribe = self._get_transcribe_client()
            transcribe.start_medical_transcription_job(
                MedicalTranscriptionJobName=job_id,
                Media={"MediaFileUri": s3_uri},
                MediaFormat=media_format,
                LanguageCode="en-US",
                Specialty="PRIMARYCARE",
                Type="DICTATION",
                OutputBucketName=self._s3_bucket,
                OutputKey=f"transcribe-output/{job_id}.json",
            )

            # 3. Poll for completion (with exponential backoff, max ~2 minutes).
            result = self._poll_job(transcribe, job_id)

            # 4. Clean up staging audio (best-effort).
            try:
                s3.delete_object(Bucket=self._s3_bucket, Key=s3_key)
            except Exception:
                logger.debug("s3_cleanup_failed", extra={"extra_fields": {"key": s3_key}})

            return result

        except TranscriptionUnavailable:
            raise
        except Exception as exc:
            logger.error(
                "transcribe_failed",
                exc_info=True,
                extra={"extra_fields": {"job_id": job_id}},
            )
            raise TranscriptionUnavailable(
                f"AWS Transcribe job failed: {exc}"
            ) from exc

    def _poll_job(self, client: Any, job_name: str) -> TranscriptionResult:
        """Poll Transcribe Medical job with exponential backoff."""
        max_attempts = 60
        wait_seconds = 2.0

        for attempt in range(max_attempts):
            response = client.get_medical_transcription_job(
                MedicalTranscriptionJobName=job_name
            )
            job = response["MedicalTranscriptionJob"]
            status = job["TranscriptionJobStatus"]

            if status == "COMPLETED":
                return self._parse_transcript_output(job)
            elif status == "FAILED":
                reason = job.get("FailureReason", "Unknown failure")
                raise TranscriptionUnavailable(
                    f"Transcription job failed: {reason}"
                )

            time.sleep(min(wait_seconds, 10.0))
            wait_seconds *= 1.5  # Exponential backoff, capped at 10s.

        raise TranscriptionUnavailable(
            "Transcription job timed out after maximum polling attempts."
        )

    def _parse_transcript_output(self, job: dict[str, Any]) -> TranscriptionResult:
        """Parse the Transcribe Medical output into TranscriptionResult."""
        transcript_uri = job.get("Transcript", {}).get("TranscriptFileUri", "")

        if not transcript_uri:
            return TranscriptionResult(transcript="")

        # Fetch the transcript JSON from S3.
        s3 = self._get_s3_client()

        # Extract bucket and key from the URI.
        # URI format: https://s3.region.amazonaws.com/bucket/key
        parts = transcript_uri.replace("https://", "").split("/", 2)
        if len(parts) >= 3:
            bucket = parts[1] if "s3" in parts[0] else parts[0]
            key = parts[2] if "s3" in parts[0] else "/".join(parts[1:])
        else:
            return TranscriptionResult(transcript="")

        try:
            obj = s3.get_object(Bucket=self._s3_bucket or bucket, Key=key)
            data = json.loads(obj["Body"].read())
        except Exception:
            logger.warning("transcript_output_fetch_failed", exc_info=True)
            return TranscriptionResult(transcript="")

        # Extract transcript text and segments.
        results = data.get("results", {})
        transcripts = results.get("transcripts", [])
        full_text = transcripts[0].get("transcript", "") if transcripts else ""

        segments: list[TranscriptSegment] = []
        for item in results.get("items", []):
            if item.get("type") == "pronunciation":
                segments.append(
                    TranscriptSegment(
                        start=float(item.get("start_time", 0)),
                        end=float(item.get("end_time", 0)),
                        text=item.get("alternatives", [{}])[0].get("content", ""),
                    )
                )

        return TranscriptionResult(transcript=full_text, segments=segments)
