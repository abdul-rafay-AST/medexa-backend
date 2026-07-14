from __future__ import annotations

from medexa.adapters.deepgram.nova_transcription import (
    DeepgramNovaTranscriptionProvider,
    _parse_deepgram_payload,
)
from medexa.config import MedexaConfig
from medexa.services.providers import build_transcription_provider
from medexa.services.transcription import UnavailableTranscriptionProvider


SAMPLE_DEEPGRAM_RESPONSE = {
    "results": {
        "channels": [
            {
                "alternatives": [
                    {
                        "transcript": "Can you flex your knee? It hurts when I bend it.",
                        "words": [
                            {
                                "word": "can",
                                "start": 0.1,
                                "end": 0.3,
                                "speaker": 0,
                                "punctuated_word": "Can",
                            },
                            {
                                "word": "you",
                                "start": 0.31,
                                "end": 0.45,
                                "speaker": 0,
                                "punctuated_word": "you",
                            },
                        ],
                    }
                ]
            }
        ],
        "utterances": [
            {
                "start": 0.1,
                "end": 1.2,
                "speaker": 0,
                "transcript": "Can you flex your knee?",
            },
            {
                "start": 1.3,
                "end": 2.8,
                "speaker": 1,
                "transcript": "It hurts when I bend it.",
            },
        ],
    }
}


def test_parse_deepgram_payload_builds_diarized_segments() -> None:
    result = _parse_deepgram_payload(SAMPLE_DEEPGRAM_RESPONSE)
    assert result.transcript.startswith("Can you flex")
    assert result.diarization_method == "deepgram"
    assert result.provider == "deepgram"
    assert len(result.segments) == 2
    assert result.segments[0].speaker_id == 0
    assert result.segments[1].speaker_id == 1


def test_segments_from_words_keeps_temporal_turns() -> None:
    from medexa.adapters.deepgram.nova_transcription import _segments_from_words

    words = [
        {"word": "can", "punctuated_word": "Can", "start": 0.0, "end": 0.2, "speaker": 0},
        {"word": "you", "punctuated_word": "you", "start": 0.2, "end": 0.3, "speaker": 0},
        {"word": "it", "punctuated_word": "It", "start": 0.4, "end": 0.5, "speaker": 1},
        {"word": "hurts", "punctuated_word": "hurts", "start": 0.5, "end": 0.7, "speaker": 1},
        {"word": "flex", "punctuated_word": "Flex", "start": 0.8, "end": 0.9, "speaker": 0},
    ]
    segments = _segments_from_words(words)
    assert len(segments) == 3
    assert [s.speaker_id for s in segments] == [0, 1, 0]
    assert segments[0].text == "Can you"
    assert segments[1].text == "It hurts"
    assert segments[2].text == "Flex"


def test_providers_prefer_deepgram_when_aws_selected_and_key_present() -> None:
    settings = MedexaConfig(
        transcription_provider="aws_transcribe",
        deepgram_api_key="dg_test_key",
        transcribe_s3_bucket="bucket",
        s3_bucket="bucket",
    )
    provider = build_transcription_provider(settings)
    from medexa.services.transcription import FallbackTranscriptionProvider

    assert isinstance(provider, FallbackTranscriptionProvider)
    assert isinstance(provider._primary, DeepgramNovaTranscriptionProvider)


def test_providers_select_deepgram_when_configured() -> None:
    settings = MedexaConfig(
        transcription_provider="deepgram",
        deepgram_api_key="dg_test_key",
    )
    provider = build_transcription_provider(settings)
    assert isinstance(provider, DeepgramNovaTranscriptionProvider)


def test_providers_fallback_without_deepgram_key() -> None:
    settings = MedexaConfig(
        transcription_provider="deepgram",
        deepgram_api_key=None,
    )
    assert isinstance(build_transcription_provider(settings), UnavailableTranscriptionProvider)
