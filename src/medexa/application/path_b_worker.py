from __future__ import annotations

import asyncio
import os
import sys
import uuid
from copy import deepcopy
from typing import Callable

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

_MAX_SAVE_ATTEMPTS = 5


class PathBWorker:
    """Event-driven Path B worker — Bedrock Converse on meaningful triggers only.

    Chat/ambient request threads must not wait for Bedrock. Outside pytest the
    worker schedules work on the event loop via ``create_task`` and returns
    immediately so Path A responses stay snappy (especially over tunnels).

    DynamoDB optimistic locking means Path A / state polls can bump ``version``
    while Bedrock runs — every Path B write therefore retries with a merge.
    """

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

        if "pytest" in sys.modules or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            await self._run(event)
            return
        asyncio.create_task(self._run(event))

    async def _run(self, event: PathBTriggerRequested) -> None:
        try:
            await self._run_inner(event)
        except Exception as exc:
            logger.exception(
                "path_b_worker_failed",
                extra={
                    "extra_fields": {
                        "session_id": event.session_id,
                        "trigger_id": event.trigger_id,
                        "error": str(exc),
                    }
                },
            )
            await self._mark_trigger_skipped(event, detail=f"path_b_error:{exc}")

    async def _run_inner(self, event: PathBTriggerRequested) -> None:
        state = await asyncio.to_thread(self._session_repo.get, event.session_id)
        if state is None:
            return

        trigger = self._find_trigger(state, event.trigger_id)
        if trigger is None or trigger.status != "pending":
            return

        if not self._settings.path_b_enabled:
            await self._save_merged(
                event.session_id,
                lambda s: self._set_trigger_status(s, event.trigger_id, "skipped"),
            )
            return

        # Mark dispatched with merge-retry — Path A often saves in the same window.
        await self._save_merged(
            event.session_id,
            lambda s: self._set_trigger_status(s, event.trigger_id, "dispatched"),
        )

        refreshed = await asyncio.to_thread(self._session_repo.get, event.session_id)
        if refreshed is None:
            return

        before = self._billing_snapshot(refreshed)
        suggestions = await self._run_assistant(refreshed, event)
        after = self._billing_snapshot(refreshed)
        if before != after:
            logger.error(
                "path_b_billing_mutation_detected",
                extra={
                    "extra_fields": {
                        "session_id": event.session_id,
                        "trigger_id": event.trigger_id,
                    }
                },
            )

        status = "completed" if suggestions else "skipped"

        def _apply_results(target: SessionState) -> None:
            self._set_trigger_status(target, event.trigger_id, status)
            existing_ids = {item.suggestion_id for item in target.assistant_suggestions}
            for suggestion in suggestions:
                if suggestion.suggestion_id in existing_ids:
                    continue
                target.assistant_suggestions.append(suggestion)
                target.audit_log.append(
                    ComplianceAuditEntry(
                        entry_id=str(uuid.uuid4()),
                        session_id=target.session_id,
                        action=AuditAction.ASSISTANT_SUGGESTION_CREATED,
                        actor="system",
                        target_id=suggestion.suggestion_id,
                        detail=f"{suggestion.kind}:{suggestion.title}",
                    )
                )

        await self._save_merged(event.session_id, _apply_results)

        for suggestion in suggestions:
            await self._realtime.publish(
                event.session_id,
                LiveEventFactory.assistant_suggestion(
                    event.session_id,
                    suggestion,
                    event_id=suggestion.suggestion_id,
                ),
            )

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

    async def _save_merged(
        self,
        session_id: str,
        mutate: Callable[[SessionState], None],
    ) -> SessionState | None:
        """Reload → apply Path B mutations → save, retrying Dynamo optimistic locks."""
        last_error: Exception | None = None
        for attempt in range(_MAX_SAVE_ATTEMPTS):
            state = await asyncio.to_thread(self._session_repo.get, session_id)
            if state is None:
                return None
            mutate(state)
            try:
                await asyncio.to_thread(self._session_repo.save, state)
                return state
            except RuntimeError as exc:
                if "Concurrent modification" not in str(exc):
                    raise
                last_error = exc
                logger.warning(
                    "path_b_save_retry",
                    extra={
                        "extra_fields": {
                            "session_id": session_id,
                            "attempt": attempt + 1,
                        }
                    },
                )
                await asyncio.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            raise last_error
        return None

    async def _mark_trigger_skipped(self, event: PathBTriggerRequested, *, detail: str) -> None:
        try:
            await self._save_merged(
                event.session_id,
                lambda state: self._apply_error_skip(state, event.trigger_id, detail),
            )
        except Exception:
            logger.exception(
                "path_b_mark_skipped_failed",
                extra={
                    "extra_fields": {
                        "session_id": event.session_id,
                        "trigger_id": event.trigger_id,
                    }
                },
            )

    @staticmethod
    def _apply_error_skip(state: SessionState, trigger_id: str, detail: str) -> None:
        PathBWorker._set_trigger_status(state, trigger_id, "skipped")
        state.audit_log.append(
            ComplianceAuditEntry(
                entry_id=str(uuid.uuid4()),
                session_id=state.session_id,
                action=AuditAction.ASSISTANT_SUGGESTION_CREATED,
                actor="system",
                target_id=trigger_id,
                detail=detail,
            )
        )

    @staticmethod
    def _set_trigger_status(state: SessionState, trigger_id: str, status: str) -> None:
        for record in state.path_b_triggers:
            if record.trigger_id == trigger_id:
                record.status = status  # type: ignore[assignment]
                return

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
