from __future__ import annotations

from pydantic import BaseModel


class ProcessChunkCommand(BaseModel):
    """Command: ingest one transcript segment through Path A only."""

    session_id: str
    chunk_text: str
    elapsed_seconds: float = 0.0
    end_elapsed_seconds: float | None = None


class TriggerPathBCommand(BaseModel):
    session_id: str
    trigger_id: str
    reason: str
    source_event_type: str


class FinalizeSessionCommand(BaseModel):
    session_id: str
    transcript: str
    total_seconds: int
