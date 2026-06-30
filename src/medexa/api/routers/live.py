from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.routers._common import refresh_and_publish, require_state
from medexa.logging_setup import get_logger
from medexa.schemas import TranscriptChunk
from medexa.services.transcription import TranscriptionUnavailable
from medexa.utils.time import now_utc

router = APIRouter(prefix="/sessions", tags=["live"])
logger = get_logger("medexa.api.live")


def _run_live_pipeline(state, text: str, container: ServiceContainer) -> None:
    """Run the deterministic billing pipeline (entity extraction, dedup
    suggestions, timers/alerts) so live billing never drifts from the clinical
    analysis layer. Mutates ``state`` in place."""
    now = now_utc()
    chunk = TranscriptChunk(
        session_id=state.session_id,
        chunk_id=str(uuid.uuid4()),
        text=text,
        start_ts=0.0,
        end_ts=0.0,
        sequence=len(state.detected_entities),
    )
    container.transcript_processor.process(state, chunk, now)


def _analyze_and_store(state, text: str, container: ServiceContainer):
    analysis = container.clinical_analyzer.analyze(text)
    state.latest_analysis = analysis
    state.transcript_text = (state.transcript_text + " " + text).strip() if text else state.transcript_text
    state.insights = m.merge_insights(state.insights, m.derive_insights(analysis))
    return analysis


@router.post("/{session_id}/analyze-transcript-chunk", response_model=c.ApiTranscriptAnalysis)
async def analyze_transcript_chunk(
    session_id: str,
    req: c.AnalyzeTranscriptChunkRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiTranscriptAnalysis:
    started = now_utc()
    state = require_state(session_id, container)

    _run_live_pipeline(state, req.chunk_text, container)
    analysis = _analyze_and_store(state, req.chunk_text, container)
    await refresh_and_publish(state, container)

    latency_ms = int((now_utc() - started).total_seconds() * 1000)
    logger.info(
        "transcript_analyzed",
        extra={"extra_fields": {"session_id": session_id, "latency_ms": latency_ms}},
    )
    return m.analysis_to_contract(analysis, state=state)


@router.post("/{session_id}/transcribe-audio", response_model=c.ApiAudioTranscriptionAnalysis)
async def transcribe_audio(
    session_id: str,
    file: UploadFile = File(...),
    container: ServiceContainer = Depends(get_container),
) -> c.ApiAudioTranscriptionAnalysis:
    state = require_state(session_id, container)
    audio = await file.read()
    try:
        result = container.transcription_provider.transcribe(audio, file.content_type)
    except TranscriptionUnavailable as exc:
        # 503: frontend cleanly falls back to browser Web Speech transcription.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    _run_live_pipeline(state, result.transcript, container)
    analysis = _analyze_and_store(state, result.transcript, container)
    await refresh_and_publish(state, container)

    base = m.analysis_to_contract(analysis, state=state)
    return c.ApiAudioTranscriptionAnalysis(
        **base.model_dump(),
        transcript=result.transcript,
        audio_segments=[
            c.ApiAudioSegment(start=s.start, end=s.end, text=s.text) for s in result.segments
        ],
    )


@router.get("/{session_id}/insights", response_model=list[c.ApiInsight])
async def get_insights(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> list[c.ApiInsight]:
    state = require_state(session_id, container)
    return [m.insight_to_contract(i) for i in state.insights]


def _set_insight_status(session_id: str, insight_id: str, status: str, container: ServiceContainer) -> c.ApiInsight:
    state = require_state(session_id, container)
    insight = next((i for i in state.insights if i.insight_id == insight_id), None)
    if insight is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    insight.status = status  # type: ignore[assignment]
    container.session_repo.save(state)
    return m.insight_to_contract(insight)


@router.post("/{session_id}/insights/{insight_id}/approve", response_model=c.ApiInsight)
async def approve_insight(
    session_id: str, insight_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiInsight:
    return _set_insight_status(session_id, insight_id, "approved", container)


@router.post("/{session_id}/insights/{insight_id}/ignore", response_model=c.ApiInsight)
async def ignore_insight(
    session_id: str, insight_id: str, container: ServiceContainer = Depends(get_container)
) -> c.ApiInsight:
    return _set_insight_status(session_id, insight_id, "ignored", container)


@router.get("/{session_id}/suggestions", response_model=list[c.ApiSuggestion])
async def get_suggestions(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> list[c.ApiSuggestion]:
    state = require_state(session_id, container)
    return [m.suggestion_to_contract(s) for s in state.suggestions]


@router.post("/{session_id}/suggestions/{suggestion_id}/apply", response_model=c.ApiSuggestion)
async def apply_suggestion(
    session_id: str,
    suggestion_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiSuggestion:
    state = require_state(session_id, container)
    suggestion = next((s for s in state.suggestions if s.suggestion_id == suggestion_id), None)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if suggestion.status == "suggested" and suggestion.cpt_code:
        suggestion.status = "applied"
        # Applying a suggestion starts billing that CPT (mutually exclusive).
        container.timer_engine.switch_segment(
            state, suggestion.cpt_code, suggestion.body_region, now_utc()
        )
        await refresh_and_publish(state, container)
    return m.suggestion_to_contract(suggestion)


@router.post("/{session_id}/suggestions/{suggestion_id}/dismiss", response_model=c.ApiSuggestion)
async def dismiss_suggestion(
    session_id: str,
    suggestion_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiSuggestion:
    state = require_state(session_id, container)
    suggestion = next((s for s in state.suggestions if s.suggestion_id == suggestion_id), None)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    suggestion.status = "dismissed"
    container.session_repo.save(state)
    return m.suggestion_to_contract(suggestion)
