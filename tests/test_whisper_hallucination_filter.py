from medexa.core.whisper_hallucination_filter import (
    filter_whisper_transcript,
    is_likely_whisper_hallucination,
)


def test_thank_you_on_silence_is_hallucination():
    assert is_likely_whisper_hallucination("Thank you.")
    assert is_likely_whisper_hallucination("thank you thank you")
    assert is_likely_whisper_hallucination("Thanks for watching")


def test_real_speech_is_not_hallucination():
    assert not is_likely_whisper_hallucination("My lower back hurts when I bend forward.")
    assert not is_likely_whisper_hallucination("Let's start therapeutic exercise.")


def test_filter_whisper_transcript_drops_no_speech_segments():
    filtered = filter_whisper_transcript(
        "Thank you.",
        [
            {
                "text": "Thank you.",
                "start": 0.0,
                "end": 1.2,
                "no_speech_prob": 0.92,
                "avg_logprob": -0.4,
            }
        ],
    )
    assert filtered == ""
