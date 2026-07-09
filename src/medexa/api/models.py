from __future__ import annotations

from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    patient_id: str | None = None
    # Optional display metadata echoed back for the frontend (e.g. dashboard /
    # debugging). The backend only needs patient_id for billing logic.
    patient_name: str | None = None
    mrn: str | None = None
    therapist_id: str | None = None
    session_type: str | None = None


class StartSessionResponse(BaseModel):
    session_id: str
    status: str
    patient_id: str | None = None
    patient_name: str | None = None
    mrn: str | None = None
    therapist_id: str | None = None
    session_type: str | None = None


class TranscriptChunkRequest(BaseModel):
    text: str
    start_ts: float = 0.0
    end_ts: float = 0.0
    sequence: int = 0


class TimerStartRequest(BaseModel):
    cpt_code: str
    body_region: str | None = None


class TimerSwitchRequest(BaseModel):
    cpt_code: str
    body_region: str | None = None


class EndSessionResponse(BaseModel):
    session_id: str
    status: str
    total_minutes: int
    total_units: int
    units_by_cpt: dict[str, int]
