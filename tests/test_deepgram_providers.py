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
