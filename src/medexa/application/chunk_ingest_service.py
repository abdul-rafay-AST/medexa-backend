from __future__ import annotations

import uuid

from medexa.domain.audit import AuditAction, ComplianceAuditEntry
from medexa.schemas import SessionState, TranscriptChunk


class ChunkIngestService:
    """Records time-stamped transcript chunks on session state (Path A ingress)."""

    def ingest(
        self,
        state: SessionState,
        text: str,
        *,
        start_ts: float,
        end_ts: float,
    ) -> TranscriptChunk:
        chunk = TranscriptChunk(
            session_id=state.session_id,
            chunk_id=str(uuid.uuid4()),
            text=text.strip(),
            start_ts=start_ts,
            end_ts=end_ts,
            sequence=len(state.transcript_chunks),
        )
        state.transcript_chunks.append(chunk)
        if chunk.text:
            state.transcript_text = (
                f"{state.transcript_text} {chunk.text}".strip() if state.transcript_text else chunk.text
            )
        state.audit_log.append(
            ComplianceAuditEntry(
                entry_id=str(uuid.uuid4()),
                session_id=state.session_id,
                action=AuditAction.CHUNK_INGESTED,
                detail=f"seq={chunk.sequence} len={len(chunk.text)}",
            )
        )
        return chunk
