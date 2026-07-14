from __future__ import annotations

from medexa.schemas import SessionState, TranscriptChunk


class TranscriptBuffer:
    """Sliding window over recent transcript chunks for Path B context.

    Defaults to the last 10 minutes or 24 chunks — whichever is smaller.
    Also tracks the last sequence sent to Path B so subsequent calls
    only include *new* text (avoids re-processing the same content).
    """

    def __init__(self, *, window_minutes: float = 10.0, max_chunks: int = 24) -> None:
        self._window_minutes = max(window_minutes, 1.0)
        self._max_chunks = max(max_chunks, 1)
        self._last_sent_sequence: dict[str, int] = {}

    def build(self, state: SessionState) -> str:
        """Return the buffered transcript text for a Path B call."""
        chunks = self._select_chunks(state.transcript_chunks)
        if not chunks and state.transcript_text:
            return state.transcript_text.strip()
        lines = [chunk.text.strip() for chunk in chunks if chunk.text.strip()]
        return "\n".join(lines)

    def build_delta(self, state: SessionState) -> str:
        """Return only *new* transcript text since the last Path B call.

        Falls back to the full windowed buffer if no prior call is recorded.
        """
        last_seq = self._last_sent_sequence.get(state.session_id, -1)
        chunks = self._select_chunks(state.transcript_chunks)
        new_chunks = [c for c in chunks if c.sequence > last_seq]
        if not new_chunks:
            # No new chunks — return full window as fallback.
            return self.build(state)
        return "\n".join(c.text.strip() for c in new_chunks if c.text.strip())

    def mark_sent(self, state: SessionState) -> None:
        """Record the latest chunk sequence as sent to Path B."""
        if state.transcript_chunks:
            ordered = sorted(state.transcript_chunks, key=lambda c: c.sequence)
            self._last_sent_sequence[state.session_id] = ordered[-1].sequence

    def _select_chunks(self, chunks: list[TranscriptChunk]) -> list[TranscriptChunk]:
        if not chunks:
            return []
        ordered = sorted(chunks, key=lambda chunk: chunk.sequence)
        if len(ordered) <= self._max_chunks:
            return ordered[-self._max_chunks :]

        latest_end = ordered[-1].end_ts
        window_start = latest_end - (self._window_minutes * 60.0)
        windowed = [chunk for chunk in ordered if chunk.end_ts >= window_start]
        if not windowed:
            windowed = ordered[-self._max_chunks :]
        return windowed[-self._max_chunks :]
