"""Amazon Transcribe (standard) adapter — AWS-native ambient STT.

Not Transcribe Medical — uses ``StartTranscriptionJob`` / ``GetTranscriptionJob``.

  * Uploads mono 16 kHz WAV (browser WebM transcoded via ffmpeg).
  * Optional speaker labels for 2-party therapy dialog.
  * Stages audio under ``transcribe/`` for S3 lifecycle expiry.
  * Job names are UUIDs (no PHI in resource names).
  * Loads transcript from the OutputKey we control.

Latency: batch jobs are typically 15–90s. Prefer Deepgram for low-latency ambient;
use this when you want AWS-only STT.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from medexa.aws.paths import S3Prefixes
from medexa.core.voice_fingerprint import AudioDecodeError, is_mono_16k_wav, transcode_to_wav_bytes
from medexa.services.transcription import (
    TranscriptionResult,
    TranscriptionUnavailable,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

MIN_AUDIO_BYTES = 400
_SPEAKER_PREFIX = "spk_"


class AwsTranscribeBatchProvider:
    """Standard Amazon Transcribe batch client (``TranscriptionProvider``)."""

    def __init__(
        self,
        *,
        region_name: str,
        s3_bucket: str,
        language_code: str = "en-US",
        enable_speaker_labels: bool = True,
        max_speaker_labels: int = 2,
        poll_timeout_seconds: float = 120.0,
        delete_staging_audio: bool = True,
    ) -> None:
        if not s3_bucket.strip():
            raise ValueError("s3_bucket is required for AwsTranscribeBatchProvider")
        self._region_name = region_name.strip()
        self._s3_bucket = s3_bucket.strip()
        self._language_code = language_code
        self._enable_speaker_labels = enable_speaker_labels
        self._max_speaker_labels = max(2, min(int(max_speaker_labels), 10))
        self._poll_timeout_seconds = max(15.0, float(poll_timeout_seconds))
        self._delete_staging_audio = delete_staging_audio
        self._s3: Any = None
        self._transcribe: Any = None

    def _s3_client(self) -> Any:
        if self._s3 is None:
            import boto3  # noqa: PLC0415

            self._s3 = boto3.client("s3", region_name=self._region_name)
        return self._s3

    def _transcribe_client(self) -> Any:
        if self._transcribe is None:
            import boto3  # noqa: PLC0415

            self._transcribe = boto3.client("transcribe", region_name=self._region_name)
        return self._transcribe

    def transcribe(self, audio: bytes, content_type: str | None = None) -> TranscriptionResult:
        if not audio or len(audio) < MIN_AUDIO_BYTES:
            raise TranscriptionUnavailable(
                "Audio chunk too short for transcription — speak a little longer."
            )

        wav_bytes, wav_ctype = self._normalize_wav(audio, content_type)
        job_id = f"medexa-{uuid.uuid4().hex[:12]}"
        input_key = f"{S3Prefixes.TRANSCRIBE}/input/{job_id}.wav"
        output_key = f"{S3Prefixes.TRANSCRIBE}/output/{job_id}.json"
        s3 = self._s3_client()
        client = self._transcribe_client()

        try:
            s3.put_object(
                Bucket=self._s3_bucket,
                Key=input_key,
                Body=wav_bytes,
                ContentType=wav_ctype,
                ServerSideEncryption="AES256",
            )

            start_kwargs: dict[str, Any] = {
                "TranscriptionJobName": job_id,
                "Media": {"MediaFileUri": f"s3://{self._s3_bucket}/{input_key}"},
                "MediaFormat": "wav",
                "LanguageCode": self._language_code,
                "OutputBucketName": self._s3_bucket,
                "OutputKey": output_key,
            }
            if self._enable_speaker_labels:
                start_kwargs["Settings"] = {
                    "ShowSpeakerLabels": True,
                    "MaxSpeakerLabels": self._max_speaker_labels,
                }

            client.start_transcription_job(**start_kwargs)
            return self._poll_and_load(client, s3, job_id, output_key)
        except TranscriptionUnavailable:
            raise
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "aws_transcribe_client_error",
                extra={"extra_fields": {"job_id": job_id, "error": str(exc)}},
            )
            raise TranscriptionUnavailable(f"Amazon Transcribe failed: {exc}") from exc
        except Exception as exc:
            logger.error(
                "aws_transcribe_failed",
                exc_info=True,
                extra={"extra_fields": {"job_id": job_id}},
            )
            raise TranscriptionUnavailable(f"Amazon Transcribe failed: {exc}") from exc
        finally:
            if self._delete_staging_audio:
                self._best_effort_delete(s3, input_key)

    def _normalize_wav(self, audio: bytes, content_type: str | None) -> tuple[bytes, str]:
        ctype = (content_type or "audio/webm").split(";")[0].strip().lower()
        if is_mono_16k_wav(audio, ctype):
            return audio, "audio/wav"
        try:
            return transcode_to_wav_bytes(audio, ctype)
        except AudioDecodeError as exc:
            raise TranscriptionUnavailable(
                "Could not decode microphone audio for Amazon Transcribe — "
                "speak a little longer and try again."
            ) from exc

    def _poll_and_load(
        self,
        client: Any,
        s3: Any,
        job_name: str,
        output_key: str,
    ) -> TranscriptionResult:
        deadline = time.monotonic() + self._poll_timeout_seconds
        wait = 1.5
        while time.monotonic() < deadline:
            response = client.get_transcription_job(TranscriptionJobName=job_name)
            job = response["TranscriptionJob"]
            status = job["TranscriptionJobStatus"]
            if status == "COMPLETED":
                return self._load_result(s3, output_key)
            if status == "FAILED":
                reason = job.get("FailureReason", "unknown")
                raise TranscriptionUnavailable(f"Transcription job failed: {reason}")
            time.sleep(wait)
            wait = min(wait * 1.4, 8.0)

        raise TranscriptionUnavailable(
            f"Transcription job timed out after {int(self._poll_timeout_seconds)}s."
        )

    def _load_result(self, s3: Any, output_key: str) -> TranscriptionResult:
        keys: list[str] = [output_key]
        if not output_key.endswith(".json"):
            keys.append(f"{output_key}.json")

        last_error: Exception | None = None
        payload: dict[str, Any] | None = None
        for key in keys:
            try:
                obj = s3.get_object(Bucket=self._s3_bucket, Key=key)
                payload = json.loads(obj["Body"].read())
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc

        if payload is None:
            prefix = output_key if output_key.endswith("/") else output_key.rsplit("/", 1)[0] + "/"
            try:
                listing = s3.list_objects_v2(Bucket=self._s3_bucket, Prefix=prefix, MaxKeys=20)
                for item in listing.get("Contents", []):
                    key = item["Key"]
                    if key.endswith(".json"):
                        obj = s3.get_object(Bucket=self._s3_bucket, Key=key)
                        payload = json.loads(obj["Body"].read())
                        break
            except Exception as exc:  # noqa: BLE001
                last_error = exc

        if payload is None:
            raise TranscriptionUnavailable(
                f"Could not load Transcribe output from s3://{self._s3_bucket}/{output_key}"
                + (f" ({last_error})" if last_error else "")
            )

        return parse_transcribe_transcript(payload)

    def _best_effort_delete(self, s3: Any, key: str) -> None:
        try:
            s3.delete_object(Bucket=self._s3_bucket, Key=key)
        except Exception:
            logger.debug(
                "aws_transcribe_staging_cleanup_failed",
                extra={"extra_fields": {"key": key}},
            )


def parse_transcribe_transcript(payload: dict[str, Any]) -> TranscriptionResult:
    """Map standard Amazon Transcribe JSON into Medexa ``TranscriptionResult``."""
    results = payload.get("results") or {}
    transcripts = results.get("transcripts") or []
    full_text = ""
    if transcripts and isinstance(transcripts[0], dict):
        full_text = str(transcripts[0].get("transcript") or "").strip()

    speaker_times = _speaker_label_intervals(results.get("speaker_labels") or {})
    segments: list[TranscriptSegment] = []

    for item in results.get("items") or []:
        if not isinstance(item, dict) or item.get("type") != "pronunciation":
            continue
        alts = item.get("alternatives") or [{}]
        content = str((alts[0] or {}).get("content") or "").strip()
        if not content:
            continue
        start = float(item.get("start_time") or 0.0)
        end = float(item.get("end_time") or start)
        speaker_id = _speaker_at(speaker_times, start)
        segments.append(
            TranscriptSegment(
                start=start,
                end=end,
                text=content,
                speaker_id=speaker_id,
            )
        )

    if not segments and full_text:
        segments = [TranscriptSegment(start=0.0, end=0.0, text=full_text)]

    collapsed = _collapse_speaker_runs(segments) if speaker_times else segments
    has_speakers = any(s.speaker_id is not None for s in collapsed)

    return TranscriptionResult(
        transcript=full_text or " ".join(s.text for s in collapsed).strip(),
        segments=collapsed,
        provider="aws_transcribe",
        diarization_method="aws_transcribe" if has_speakers else "none",
        speaker_confidence=0.85 if has_speakers else 0.0,
    )


def _speaker_label_intervals(speaker_labels: dict[str, Any]) -> list[tuple[float, float, int]]:
    intervals: list[tuple[float, float, int]] = []
    for segment in speaker_labels.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        label = str(segment.get("speaker_label") or "")
        speaker_id = _parse_speaker_label(label)
        if speaker_id is None:
            continue
        start = float(segment.get("start_time") or 0.0)
        end = float(segment.get("end_time") or start)
        intervals.append((start, end, speaker_id))
    intervals.sort(key=lambda row: row[0])
    return intervals


def _parse_speaker_label(label: str) -> int | None:
    text = label.strip().lower()
    if text.startswith(_SPEAKER_PREFIX):
        try:
            return int(text[len(_SPEAKER_PREFIX) :])
        except ValueError:
            return None
    if text.isdigit():
        return int(text)
    return None


def _speaker_at(intervals: list[tuple[float, float, int]], t: float) -> int | None:
    for start, end, speaker_id in intervals:
        if start <= t <= end + 1e-3:
            return speaker_id
    best: int | None = None
    best_dist = float("inf")
    for start, end, speaker_id in intervals:
        mid = (start + end) / 2.0
        dist = abs(mid - t)
        if dist < best_dist:
            best_dist = dist
            best = speaker_id
    return best if best_dist < 2.0 else None


def _collapse_speaker_runs(segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
    if not segments:
        return []
    collapsed: list[TranscriptSegment] = []
    current = segments[0]
    words = [current.text]
    for segment in segments[1:]:
        if segment.speaker_id == current.speaker_id:
            words.append(segment.text)
            current = current.model_copy(update={"end": segment.end, "text": " ".join(words)})
        else:
            collapsed.append(current)
            current = segment
            words = [segment.text]
    collapsed.append(current)
    return collapsed
