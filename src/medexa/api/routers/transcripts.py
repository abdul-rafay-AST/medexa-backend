from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from medexa.api import contracts as c
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import require_state
from medexa.schemas import SessionState

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _to_api_transcript(state: SessionState) -> c.ApiTranscript:
    summarized = bool(state.transcript_summary)
    return c.ApiTranscript(
        id=state.session_id,
        patient_name=state.patient_name or "",
        avatar=state.patient_display.avatar,
        time=state.patient_display.session_time or state.created_at.isoformat(),
        status="SUMMARIZED" if summarized else "SUMMARY PENDING",
        summary=state.transcript_summary or "",
        transcript=state.transcript_text,
    )


@router.get("", response_model=list[c.ApiTranscript])
async def list_transcripts(
    container: ServiceContainer = Depends(get_container),
) -> list[c.ApiTranscript]:
    # Recordings list = every session that captured transcript text.
    return [
        _to_api_transcript(s)
        for s in container.session_repo.list_all()
        if s.transcript_text
    ]


@router.post("/{transcript_id}/generate-summary", response_model=c.ApiTranscript)
async def generate_summary(
    transcript_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiTranscript:
    state = require_state(transcript_id, container)
    if not state.transcript_text:
        raise HTTPException(status_code=409, detail="No transcript captured for this session")

    analysis = state.latest_analysis
    if analysis and (analysis.possible_diagnoses or analysis.cpt_suggestions):
        impressions = "; ".join(analysis.possible_diagnoses[:3])
        interventions = ", ".join(s.display_name for s in analysis.cpt_suggestions)
        summary = f"{analysis.summary} Impressions: {impressions or 'none noted'}."
        if interventions:
            summary += f" Interventions: {interventions}."
    else:
        clean = " ".join(state.transcript_text.split())
        summary = clean[:280] + ("..." if len(clean) > 280 else "")

    state.transcript_summary = summary
    container.session_repo.save(state)
    return _to_api_transcript(state)
