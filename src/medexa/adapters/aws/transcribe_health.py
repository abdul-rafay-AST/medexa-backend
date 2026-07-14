"""Non-mutating Amazon Transcribe (standard) health probe."""

from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError


def probe_transcribe(*, region: str, bucket: str | None) -> tuple[bool, str]:
    """Confirm list API + optional S3 head — does not start a transcription job."""
    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        return False, "boto3 not installed"

    region_name = (region or "").strip() or "us-east-2"
    try:
        client = boto3.client("transcribe", region_name=region_name)
        client.list_transcription_jobs(MaxResults=1)
    except (ClientError, BotoCoreError) as exc:
        return False, f"transcribe list failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"transcribe client failed: {exc}"

    if not bucket:
        return False, "MEDEXA_TRANSCRIBE_S3_BUCKET / MEDEXA_S3_BUCKET not set"

    try:
        s3 = boto3.client("s3", region_name=region_name)
        s3.head_bucket(Bucket=bucket)
    except (ClientError, BotoCoreError) as exc:
        return False, f"s3 bucket check failed: {exc}"

    return True, f"amazon transcribe ok bucket={bucket}"
