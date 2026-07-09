from __future__ import annotations

from medexa.schemas import SessionState, TranscriptChunk


class TranscriptBuffer:
    """Sliding window over recent transcript chunks for Path B context."""

    def __init__(self, *, window_minutes: float = 10.0, max_chunks: int = 24) -> None:
        self._window_minutes = max(window_minutes, 1.0)
        self._max_chunks = max(max_chunks, 1)

    def build(self, state: SessionState) -> str:
        chunks = self._select_chunks(state.transcript_chunks)
        if not chunks and state.transcript_text:
            return state.transcript_text.strip()
        lines = [chunk.text.strip() for chunk in chunks if chunk.text.strip()]
        return "\n".join(lines)

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
