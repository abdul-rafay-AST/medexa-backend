from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from medexa.adapters.events.in_process_bus import InProcessEventBus
from medexa.application.path_a_processor import PathAResult
from medexa.application.path_b_worker import PathBWorker
from medexa.application.path_b_trigger_evaluator import PathBTriggerEvaluator
from medexa.domain.events import PathBTriggerRequested
from medexa.domain.live_events import LiveEventFactory
from medexa.logging_setup import get_logger
from medexa.ports.realtime import RealtimePort
from medexa.schemas import PathBTriggerRecord, SessionState
from medexa.state.session_state_repository import SessionStateRepository

logger = get_logger("medexa.application.events")


class PathAEventDispatcher:
    def __init__(
        self,
        event_bus: InProcessEventBus,
        evaluator: PathBTriggerEvaluator,
        realtime: RealtimePort,
        session_repo: SessionStateRepository,
    ) -> None:
        self._bus = event_bus
        self._evaluator = evaluator
        self._realtime = realtime
        self._session_repo = session_repo

    async def dispatch(self, state: SessionState, result: PathAResult, *, now: datetime) -> None:
        for event in result.events:
            await self._bus.publish(event)

        for alert in result.new_alerts:
            event_id = str(uuid.uuid4())
            if alert.alert_type == "pre_auth_required":
                await self._realtime.publish(
                    state.session_id,
                    LiveEventFactory.pre_auth_warning(state.session_id, alert, event_id=event_id),
                )
            elif alert.alert_type == "billing_conflict":
                await self._realtime.publish(
                    state.session_id,
                    LiveEventFactory.billing_conflict(state.session_id, alert, event_id=event_id),
                )
            elif alert.severity == "high":
                await self._realtime.publish(
                    state.session_id,
                    LiveEventFactory.alert(state.session_id, alert, event_id=event_id),
                )

        decision = self._evaluator.evaluate_batch(
            result.events, now=now, chunk_text=result.chunk.text
        )
        snapshot_id = str(uuid.uuid4())
        await self._realtime.publish(
            state.session_id,
            LiveEventFactory.path_a_snapshot(state.session_id, result.panel, event_id=snapshot_id),
        )
        timer_id = str(uuid.uuid4())
        await self._realtime.publish(
            state.session_id,
            LiveEventFactory.timer_update(
                state.session_id,
                event_id=timer_id,
                session_timer_sec=result.panel.session_timer_sec,
                active_cpt=state.active_cpt,
            ),
        )

        if decision is not None:
            trigger_event = self._evaluator.build_trigger_event(state.session_id, decision)
            await self._register_trigger(state, trigger_event)
            await self._bus.publish(trigger_event)

    async def _register_trigger(self, state: SessionState, event: PathBTriggerRequested) -> None:
        record = PathBTriggerRecord(
            trigger_id=event.trigger_id,
            session_id=event.session_id,
            reason=event.reason,
            source_event_type=event.source_event_type,
            status="pending",
            created_at=event.occurred_at,
        )
        state.path_b_triggers.append(record)
        await asyncio.to_thread(self._session_repo.save, state)
        await self._realtime.publish(
            event.session_id,
            LiveEventFactory.path_b_trigger(event.session_id, record, event_id=event.trigger_id),
        )
        logger.info(
            "path_b_trigger_requested",
            extra={
                "extra_fields": {
                    "session_id": event.session_id,
                    "trigger_id": event.trigger_id,
                    "reason": event.reason,
                    "source": event.source_event_type,
                }
            },
        )


def register_event_handlers(
    bus: InProcessEventBus,
    *,
    path_b_worker: PathBWorker,
) -> None:
    bus.subscribe("path_b_trigger_requested", path_b_worker.handle)
