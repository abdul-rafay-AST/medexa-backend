from __future__ import annotations

from medexa.adapters.aws.transcribe_batch import parse_transcribe_transcript
from medexa.config import MedexaConfig
from medexa.services.providers import build_transcription_provider
from medexa.services.transcription import AwsTranscribeProvider, UnavailableTranscriptionProvider


def test_parse_transcribe_transcript_with_speaker_labels() -> None:
    payload = {
        "results": {
            "transcripts": [{"transcript": "Hello patient how is your shoulder pain"}],
            "speaker_labels": {
                "speakers": 2,
                "segments": [
                    {"speaker_label": "spk_0", "start_time": "0.0", "end_time": "1.2"},
                    {"speaker_label": "spk_1", "start_time": "1.2", "end_time": "3.0"},
                ],
            },
            "items": [
                {
                    "type": "pronunciation",
                    "start_time": "0.0",
                    "end_time": "0.4",
                    "alternatives": [{"content": "Hello"}],
                },
                {
                    "type": "pronunciation",
                    "start_time": "0.4",
                    "end_time": "1.0",
                    "alternatives": [{"content": "patient"}],
                },
                {
                    "type": "pronunciation",
                    "start_time": "1.3",
                    "end_time": "1.6",
                    "alternatives": [{"content": "how"}],
                },
                {
                    "type": "pronunciation",
                    "start_time": "1.6",
                    "end_time": "2.8",
                    "alternatives": [{"content": "is"}],
                },
            ],
        }
    }

    result = parse_transcribe_transcript(payload)
    assert result.provider == "aws_transcribe"
    assert result.diarization_method == "aws_transcribe"
    assert "Hello" in result.transcript
    assert any(seg.speaker_id == 0 for seg in result.segments)
    assert any(seg.speaker_id == 1 for seg in result.segments)
    assert len(result.segments) <= 4


def test_build_transcription_provider_aws_requires_bucket() -> None:
    settings = MedexaConfig(
        transcription_provider="aws_transcribe",
        s3_bucket=None,
        transcribe_s3_bucket=None,
        deepgram_api_key=None,
    )
    provider = build_transcription_provider(settings)
    assert isinstance(provider, UnavailableTranscriptionProvider)


def test_build_transcription_provider_aws_with_bucket() -> None:
    settings = MedexaConfig(
        transcription_provider="aws_transcribe",
        aws_region="us-east-2",
        s3_bucket="medexa-storage",
        transcribe_enable_speaker_labels=True,
        deepgram_api_key=None,
    )
    provider = build_transcription_provider(settings)
    assert isinstance(provider, AwsTranscribeProvider)


def test_build_transcription_provider_aws_with_deepgram_failover() -> None:
    from medexa.services.transcription import FallbackTranscriptionProvider

    settings = MedexaConfig(
        transcription_provider="aws_transcribe",
        aws_region="us-east-2",
        s3_bucket="medexa-storage",
        deepgram_api_key="dg_test_key",
    )
    provider = build_transcription_provider(settings)
    assert isinstance(provider, FallbackTranscriptionProvider)


def test_aws_provider_missing_bucket_raises_unavailable() -> None:
    provider = AwsTranscribeProvider(region_name="us-east-2", s3_bucket=None)
    try:
        provider.transcribe(b"x" * 500, "audio/wav")
        raise AssertionError("expected TranscriptionUnavailable")
    except Exception as exc:
        assert "not configured" in str(exc).lower() or "bucket" in str(exc).lower()
