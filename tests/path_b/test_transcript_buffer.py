from __future__ import annotations

from medexa.application.transcript_buffer import TranscriptBuffer
from medexa.schemas import SessionState, TranscriptChunk


def test_transcript_buffer_uses_recent_chunks() -> None:
    state = SessionState(session_id="s1")
    state.transcript_chunks = [
        TranscriptChunk(
            session_id="s1",
            chunk_id="c1",
            text="older chunk",
            start_ts=0,
            end_ts=60,
            sequence=0,
        ),
        TranscriptChunk(
            session_id="s1",
            chunk_id="c2",
            text="recent therapeutic exercise",
            start_ts=540,
            end_ts=555,
            sequence=1,
        ),
    ]
    buffer = TranscriptBuffer(window_minutes=5, max_chunks=10)
    text = buffer.build(state)
    assert "recent therapeutic exercise" in text


def test_transcript_buffer_falls_back_to_transcript_text() -> None:
    state = SessionState(session_id="s1", transcript_text="full session transcript")
    buffer = TranscriptBuffer()
    assert buffer.build(state) == "full session transcript"
