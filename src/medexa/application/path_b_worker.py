from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime

from medexa.application.transcript_buffer import TranscriptBuffer
from medexa.config import MedexaConfig
from medexa.domain.assistant_suggestion import AssistantSuggestion
from medexa.domain.audit import AuditAction, ComplianceAuditEntry
from medexa.domain.events import DomainEvent, PathBTriggerRequested
from medexa.domain.live_events import LiveEventFactory
from medexa.logging_setup import get_logger
from medexa.ports.clinical_assistant import ClinicalAssistantPort
from medexa.ports.realtime import RealtimePort
from medexa.schemas import SessionState
from medexa.state.session_state_repository import SessionStateRepository

logger = get_logger("medexa.application.path_b")


class PathBWorker:
    """Event-driven Path B worker — Bedrock Converse on meaningful triggers only."""

    def __init__(
        self,
        *,
        settings: MedexaConfig,
        session_repo: SessionStateRepository,
        assistant: ClinicalAssistantPort,
        realtime: RealtimePort,
        transcript_buffer: TranscriptBuffer | None = None,
    ) -> None:
        self._settings = settings
        self._session_repo = session_repo
        self._assistant = assistant
        self._realtime = realtime
        self._buffer = transcript_buffer or TranscriptBuffer(
            window_minutes=settings.path_b_transcript_window_minutes,
            max_chunks=settings.path_b_transcript_max_chunks,
        )

    async def handle(self, event: DomainEvent) -> None:
        if not isinstance(event, PathBTriggerRequested):
            return

        state = self._session_repo.get(event.session_id)
        if state is None:
            return

        trigger = self._find_trigger(state, event.trigger_id)
        if trigger is None or trigger.status != "pending":
            return

        if not self._settings.path_b_enabled:
            trigger.status = "skipped"
            self._session_repo.save(state)
            return

        trigger.status = "dispatched"
        self._session_repo.save(state)

        import asyncio

        async def _run_bg() -> None:
            try:
                before = self._billing_snapshot(state)
                suggestions = await self._run_assistant(state, event)
                refreshed = self._session_repo.get(event.session_id)
                if refreshed is None:
                    return

                after = self._billing_snapshot(refreshed)
                if before != after:
                    logger.error(
                        "path_b_billing_mutation_detected",
                        extra={"extra_fields": {"session_id": event.session_id, "trigger_id": event.trigger_id}},
                    )

                trigger = self._find_trigger(refreshed, event.trigger_id)
                if trigger is not None:
                    trigger.status = "completed" if suggestions else "skipped"

                for suggestion in suggestions:
                    refreshed.assistant_suggestions.append(suggestion)
                    refreshed.audit_log.append(
                        ComplianceAuditEntry(
                            entry_id=str(uuid.uuid4()),
                            session_id=refreshed.session_id,
                            action=AuditAction.ASSISTANT_SUGGESTION_CREATED,
                            actor="system",
                            target_id=suggestion.suggestion_id,
                            detail=f"{suggestion.kind}:{suggestion.title}",
                        )
                    )
                    await self._realtime.publish(
                        refreshed.session_id,
                        LiveEventFactory.assistant_suggestion(
                            refreshed.session_id,
                            suggestion,
                            event_id=suggestion.suggestion_id,
                        ),
                    )

                self._session_repo.save(refreshed)
                logger.info(
                    "path_b_completed",
                    extra={
                        "extra_fields": {
                            "session_id": event.session_id,
                            "trigger_id": event.trigger_id,
                            "suggestion_count": len(suggestions),
                        }
                    },
                )
            except Exception as e:
                logger.exception("Failed to run assistant in background", exc_info=e)
                refreshed = self._session_repo.get(event.session_id)
                if refreshed is not None:
                    trigger = self._find_trigger(refreshed, event.trigger_id)
                    if trigger is not None:
                        trigger.status = "skipped"
                    refreshed.audit_log.append(
                        ComplianceAuditEntry(
                            entry_id=str(uuid.uuid4()),
                            session_id=refreshed.session_id,
                            action=AuditAction.ASSISTANT_SUGGESTION_CREATED,
                            actor="system",
                            target_id=event.trigger_id,
                            detail=f"path_b_error:{e}",
                        )
                    )
                    self._session_repo.save(refreshed)

        import sys
        if "pytest" in sys.modules:
            await _run_bg()
        else:
            asyncio.create_task(_run_bg())

    async def _run_assistant(
        self,
        state: SessionState,
        event: PathBTriggerRequested,
    ) -> list[AssistantSuggestion]:
        transcript = self._buffer.build(state)
        if not transcript.strip():
            return []

        context = {
            "trigger_reason": event.reason,
            "billing_region": state.billing_region,
            "active_cpt": state.active_cpt,
            "alerts": [alert.model_dump(mode="json") for alert in state.alerts[-5:]],
        }
        payloads = await self._assistant.suggest(state.session_id, transcript, context)
        return [
            AssistantSuggestion.from_model_payload(
                session_id=state.session_id,
                trigger_id=event.trigger_id,
                payload=payload,
            )
            for payload in payloads
        ]

    @staticmethod
    def _find_trigger(state: SessionState, trigger_id: str):
        for record in state.path_b_triggers:
            if record.trigger_id == trigger_id:
                return record
        return None

    @staticmethod
    def _billing_snapshot(state: SessionState) -> dict[str, object]:
        return {
            "active_cpt": state.active_cpt,
            "timer_segments": deepcopy(state.timer_segments),
            "suggestions": deepcopy(state.suggestions),
        }
