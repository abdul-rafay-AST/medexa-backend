from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from medexa.api import contracts as c
from medexa.api import mappers as m
from medexa.api.dependencies import ServiceContainer, get_container
from medexa.api.body_region_labels import body_region_display
from medexa.api.routers._common import billing_now, refresh_and_publish, require_state
from medexa.core.speaker_role_classifier import format_labeled_utterance
from medexa.core.voice_fingerprint import resolve_chunk_duration_seconds
from medexa.config import settings as app_settings
from medexa.logging_setup import get_logger
from medexa.schemas import Alert, ProtocolInsight, SessionState, TranscriptUtterance
from medexa.services.transcription import TranscriptionUnavailable, TranscriptSegment
from medexa.utils.time import now_utc

router = APIRouter(prefix="/sessions", tags=["live"])
logger = get_logger("medexa.api.live")


def _sync_ncci_billing_insights(state: SessionState, container: ServiceContainer) -> None:
    """Push Modifier 59 / NCCI billing insights using region-aware conflict rules."""
    segments = [(seg.cpt_code, seg.body_region) for seg in state.timer_segments]
    alerts = container.ncci_checker.check_conflicts(state.session_id, segments)
    fresh: list[ProtocolInsight] = []
    for alert in alerts:
        if len(alert.cpt_codes) != 2:
            continue
        code_a, code_b = sorted(alert.cpt_codes)
        region_key = alert.body_region or "any"
        fresh.append(
            ProtocolInsight(
                insight_id=m._insight_id("billing", f"{code_a}-{code_b}-{region_key}"),
                type="billing",
                label=f"NCCI: {code_a} + {code_b}",
                question=(
                    "Apply Modifier 59?"
                    if "Modifier 59" in alert.message
                    else "Review billing conflict"
                ),
                description=alert.message,
                status="approved",
            )
        )
    if fresh:
        state.insights = m.merge_insights(state.insights, fresh)


def _elapsed_bounds(state: SessionState, req: c.AnalyzeTranscriptChunkRequest) -> tuple[float, float]:
    """Resolve chunk window from simulated clock, MM:SS labels, or prior elapsed."""
    if req.elapsed_seconds is not None:
        start = float(max(0, req.elapsed_seconds))
    else:
        start = float(state.client_elapsed_seconds or 0)
        if req.start_time and ":" in req.start_time:
            parts = req.start_time.split(":")
            if len(parts) == 2:
                start = float(int(parts[0]) * 60 + int(parts[1]))

    duration = max(1, int(req.duration_seconds or 15))
    end = start + float(duration)
    if req.end_time and ":" in req.end_time:
        parts = req.end_time.split(":")
        if len(parts) == 2:
            end = float(int(parts[0]) * 60 + int(parts[1]))
    if end <= start:
        end = start + float(duration)
    return start, end


@router.post("/{session_id}/analyze-transcript-chunk", response_model=c.ApiTranscriptAnalysis)
async def analyze_transcript_chunk(
    session_id: str,
    req: c.AnalyzeTranscriptChunkRequest,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiTranscriptAnalysis:
    """Path A on every chunk — deterministic rules. May enqueue Path B triggers."""
    wall_start = now_utc()
    state = require_state(session_id, container)
    runtime = container.runtime_for_state(state.billing_region)

    start_ts, end_ts = _elapsed_bounds(state, req)
    state.client_elapsed_seconds = int(end_ts)
    # Billing segments use wall clock while the session is live.
    now = billing_now(state)

    chunk = container.chunk_ingest.ingest(
        state, req.chunk_text, start_ts=start_ts, end_ts=end_ts
    )
    result = runtime.path_a_processor.process(state, chunk, now)

    await container.path_a_dispatcher.dispatch(state, result, now=now)

    state.last_updated = now
    container.session_repo.save(state)

    analysis = runtime.path_a_snapshot.build_analysis(state, req.chunk_text, chunk.chunk_id)
    state.latest_analysis = analysis
    container.session_repo.save(state)

    latency_ms = int((now_utc() - wall_start).total_seconds() * 1000)
    logger.info(
        "path_a_chunk_processed",
        extra={
            "extra_fields": {
                "session_id": session_id,
                "latency_ms": latency_ms,
                "entities": len(result.entities),
                "elapsed_seconds": int(end_ts),
            }
        },
    )
    return runtime.path_a_snapshot.to_contract(analysis, state)


@router.post("/{session_id}/transcribe-audio", response_model=c.ApiAudioTranscriptionAnalysis)
async def transcribe_audio(
    session_id: str,
    file: UploadFile = File(...),
    client_pitch_hz: float | None = Form(default=None),
    client_duration_seconds: float | None = Form(default=None),
    container: ServiceContainer = Depends(get_container),
) -> c.ApiAudioTranscriptionAnalysis:
    state = require_state(session_id, container)
    runtime = container.runtime_for_state(state.billing_region)
    audio = await file.read()
    try:
        result = container.transcription_provider.transcribe(audio, file.content_type)
    except TranscriptionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    chunk_duration = resolve_chunk_duration_seconds(
        audio,
        file.content_type,
        client_duration_seconds=client_duration_seconds,
    )
    now = billing_now(state)
    elapsed = float(state.client_elapsed_seconds or 0)
    end_ts = elapsed + chunk_duration
    state.client_elapsed_seconds = int(end_ts)

    transcript = result.transcript.strip()
    if not transcript:
        state.last_updated = now
        container.session_repo.save(state)
        analysis = state.latest_analysis or runtime.path_a_snapshot.build_analysis(state, "", "")
        base = runtime.path_a_snapshot.to_contract(analysis, state)
        return c.ApiAudioTranscriptionAnalysis(
            **base.model_dump(),
            transcript="",
            speaker=state.last_ambient_speaker or "patient",
            speaker_confidence=0.0,
            at_seconds=int(elapsed),
            end_seconds=int(end_ts),
            audio_segments=[],
        )

    diarized = container.ambient_diarization_resolver.resolve(
        audio=audio,
        content_type=file.content_type,
        transcript=transcript,
        transcription=result,
        state=state,
        client_pitch_hz=client_pitch_hz,
        chunk_start_ts=elapsed,
        chunk_end_ts=end_ts,
    )
    classification_role = diarized.primary_role
    classification_confidence = diarized.confidence
    classification_method = diarized.method
    diarized_segments = diarized.segments

    state.last_ambient_speaker = classification_role
    labeled_text = " ".join(
        format_labeled_utterance(utterance.speaker, utterance.text)
        for utterance in diarized.utterances
        if utterance.text.strip()
    ) or format_labeled_utterance(classification_role, transcript)

    chunk = container.chunk_ingest.ingest(
        state, labeled_text, start_ts=elapsed, end_ts=end_ts
    )
    chunk.speaker_role = classification_role

    for utterance in diarized.utterances:
        if not utterance.text.strip():
            continue
        start_ts = elapsed + utterance.start_offset
        end_ts_utt = (
            elapsed + utterance.end_offset
            if utterance.end_offset > utterance.start_offset
            else end_ts
        )
        state.transcript_utterances.append(
            TranscriptUtterance(
                utterance_id=str(uuid.uuid4()),
                speaker=utterance.speaker,
                text=utterance.text.strip(),
                start_ts=start_ts,
                end_ts=end_ts_utt,
                confidence=utterance.confidence,
                source_chunk_id=chunk.chunk_id,
                diarization_method=utterance.method,
            )
        )

    path_result = runtime.path_a_processor.process(state, chunk, now)
    await container.path_a_dispatcher.dispatch(state, path_result, now=now)
    state.last_updated = now
    container.session_repo.save(state)

    analysis = runtime.path_a_snapshot.build_analysis(state, transcript, chunk.chunk_id)
    base = runtime.path_a_snapshot.to_contract(analysis, state)

    def _segment_speaker(segment: TranscriptSegment) -> str:
        return segment.speaker_role or classification_role

    return c.ApiAudioTranscriptionAnalysis(
        **base.model_dump(),
        transcript=transcript,
        speaker=classification_role,
        speaker_confidence=classification_confidence,
        diarization_method=classification_method,
        transcription_provider=result.provider,
        at_seconds=int(elapsed),
        end_seconds=int(end_ts),
        audio_segments=[
            c.ApiAudioSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                speaker=_segment_speaker(segment),
            )
            for segment in diarized_segments
        ]
        or [
            c.ApiAudioSegment(
                start=elapsed,
                end=end_ts,
                text=transcript,
                speaker=classification_role,
            )
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


@router.get("/{session_id}/assistant-suggestions", response_model=list[c.ApiAssistantSuggestion])
async def get_assistant_suggestions(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> list[c.ApiAssistantSuggestion]:
    """Path B assistant output — separate from billing CPT suggestions."""
    state = require_state(session_id, container)
    return [m.assistant_suggestion_to_contract(s) for s in state.assistant_suggestions]


@router.get("/{session_id}/live-pipeline", response_model=c.ApiLivePipelineSnapshot)
async def get_live_pipeline(
    session_id: str,
    container: ServiceContainer = Depends(get_container),
) -> c.ApiLivePipelineSnapshot:
    """Pollable Path A / B / C snapshot for local step-by-step testing UIs."""
    state = require_state(session_id, container)
    now = billing_now(state)
    runtime = container.runtime_for_state(state.billing_region)
    metrics = runtime.billing_engine.compute_metrics(state, now)
    panel = runtime.insights_builder.build(state, now)

    last_trigger = state.path_b_triggers[-1] if state.path_b_triggers else None
    path_b_status = "idle"
    if last_trigger is not None:
        path_b_status = last_trigger.status
    elif app_settings.path_b_enabled:
        path_b_status = "armed"
    else:
        path_b_status = "disabled"

    path_c_ready = state.status == "ended" or state.finalized_at is not None
    cpt_elapsed = metrics.running_segment_seconds
    cpt_display = (
        container.cpt_metadata.get_display_name(state.active_cpt) if state.active_cpt else None
    )
    return c.ApiLivePipelineSnapshot(
        session_id=state.session_id,
        billing_region=state.billing_region,
        elapsed_seconds=int(state.client_elapsed_seconds or 0),
        path_a=c.ApiPathAStatus(
            status="live",
            entity_count=len(state.detected_entities),
            alert_count=len(state.alerts),
            suggestion_count=len(state.suggestions),
            active_cpt=state.active_cpt,
            cpt_display_name=cpt_display,
            session_timer_sec=metrics.timed_pool_seconds,
            cpt_elapsed_seconds=cpt_elapsed,
            units=panel.eight_minute_rule.total_units if panel.eight_minute_rule else 0,
        ),
        path_b=c.ApiPathBStatus(
            enabled=app_settings.path_b_enabled,
            status=path_b_status,
            trigger_count=len(state.path_b_triggers),
            suggestion_count=len(state.assistant_suggestions),
            triggers=[
                c.ApiPathBTriggerStatus(
                    id=t.trigger_id,
                    reason=t.reason,
                    status=t.status,
                    created_at=t.created_at.isoformat(),
                )
                for t in state.path_b_triggers[-5:]
            ],
        ),
        path_c=c.ApiPathCStatus(
            status="finalized" if path_c_ready else "pending",
            has_soap=bool(
                state.soap.subjective.chief_complaint or state.soap.assessment.diagnosis_summary
            ),
            has_summary=bool(state.patient_summary.summary),
            review_open_count=(
                state.documentation_review.open_count if state.documentation_review else 0
            ),
        ),
        insights=[m.insight_to_contract(i) for i in state.insights],
        billing_suggestions=[m.suggestion_to_contract(s) for s in state.suggestions],
        assistant_suggestions=[
            m.assistant_suggestion_to_contract(s) for s in state.assistant_suggestions
        ],
        entities=[
            c.ApiExtractedEntity(
                id=f"{e.source_chunk_id}:{e.matched_phrase}:{e.possible_cpt or ''}",
                phrase=e.matched_phrase,
                region=e.body_region,
                display_region=body_region_display(e.body_region),
                cpt=e.possible_cpt,
                icd10=None,
                is_billable=bool(e.is_billable and e.possible_cpt),
            )
            for e in state.detected_entities
        ],
        diarized_utterances=[
            c.ApiDiarizedUtterance(
                id=u.utterance_id,
                speaker=u.speaker,
                text=u.text,
                at_seconds=int(u.start_ts),
                end_seconds=int(u.end_ts),
                confidence=u.confidence,
                diarization_method=u.diarization_method,
            )
            for u in state.transcript_utterances
        ],
        transcript_preview=(state.transcript_text or "")[-400:],
    )


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
        state.status = "active"
        now = billing_now(state)
        active_segments = [
            (seg.cpt_code, seg.body_region)
            for seg in state.timer_segments
            if seg.stop_time is None
        ]
        for seg_cpt, seg_region in active_segments:
            if seg_cpt == suggestion.cpt_code:
                continue
            rule = container.ncci_checker.check_conflict(suggestion.cpt_code, seg_cpt)
            if not rule:
                continue
            if rule["body_region_sensitive"]:
                region = suggestion.body_region
                if region is None or region != seg_region:
                    continue
            conflict_key = f"{suggestion.cpt_code}-{seg_cpt}"
            if not any(
                a.alert_type == "ncci_conflict" and conflict_key in a.message for a in state.alerts
            ):
                modifier_hint = (
                    " Modifier 59 may apply."
                    if rule.get("modifier_59_possible")
                    else ""
                )
                state.alerts.append(
                    Alert(
                        alert_id=str(uuid.uuid4()),
                        session_id=session_id,
                        alert_type="ncci_conflict",
                        severity="medium",
                        message=(
                            f"NCCI conflict {conflict_key}: {rule['explanation']}{modifier_hint}"
                        ),
                        cpt_codes=[suggestion.cpt_code, seg_cpt],
                        body_region=suggestion.body_region,
                    )
                )
        suggestion.status = "applied"
        container.timer_engine.switch_segment(
            state, suggestion.cpt_code, suggestion.body_region, now
        )
        for insight in state.insights:
            if insight.type == "detected" and suggestion.cpt_code in insight.question:
                insight.status = "approved"
        _sync_ncci_billing_insights(state, container)
        container.session_repo.save(state)
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
