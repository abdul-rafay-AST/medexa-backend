from __future__ import annotations

import pytest

from medexa.adapters.events.in_process_bus import InProcessEventBus
from medexa.adapters.realtime.in_process_broker import InProcessBroker
from medexa.adapters.realtime.sse_adapter import SseRealtimeAdapter
from medexa.adapters.clinical_assistant.no_op import NoOpClinicalAssistant
from medexa.application.event_handlers import PathAEventDispatcher, register_event_handlers
from medexa.application.path_b_trigger_evaluator import PathBTriggerEvaluator
from medexa.application.path_b_worker import PathBWorker
from medexa.config import settings
from medexa.application.path_a_processor import PathAResult
from medexa.domain.events import ActivityChanged, ChunkProcessed
from medexa.schemas import InsightsPanel, SessionState, TranscriptChunk
from medexa.state import InMemorySessionStateRepository
from medexa.utils.time import now_utc


@pytest.mark.asyncio
async def test_dispatcher_publishes_path_b_trigger_without_bedrock():
    repo = InMemorySessionStateRepository()
    state = SessionState(session_id="s1", patient_id="p1")
    repo.save(state)

    bus = InProcessEventBus()
    broker = InProcessBroker()
    realtime = SseRealtimeAdapter(broker)
    evaluator = PathBTriggerEvaluator(interval_seconds=30)
    worker = PathBWorker(
        settings=settings,
        session_repo=repo,
        assistant=NoOpClinicalAssistant(),
        realtime=realtime,
    )
    dispatcher = PathAEventDispatcher(bus, evaluator, realtime, repo)
    register_event_handlers(bus, path_b_worker=worker)

    chunk = TranscriptChunk(
        session_id="s1",
        chunk_id="c1",
        text="therapeutic exercise",
        start_ts=0,
        end_ts=15,
        sequence=0,
    )
    panel = InsightsPanel(session_id="s1", session_timer_sec=15)
    events = [
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=1,
            suggestion_count=1,
        ),
        ActivityChanged(
            session_id="s1",
            activity_label="therapeutic_exercise",
            cpt_code="97110",
            body_region="knee",
        ),
    ]
    result = PathAResult(chunk=chunk, entities=[], panel=panel, events=events, new_alerts=[])
    queue = broker.subscribe("s1")
    await dispatcher.dispatch(state, result, now=now_utc())

    updated = repo.get("s1")
    assert updated is not None
    assert len(updated.path_b_triggers) == 1
    assert updated.path_b_triggers[0].status == "skipped"
    assert updated.path_b_triggers[0].source_event_type == "activity_changed"

    snapshot = await queue.get()
    assert snapshot is not None
    assert snapshot.kind == "path_a_snapshot"
    timer = await queue.get()
    assert timer is not None
    assert timer.kind == "timer_update"
    trigger = await queue.get()
    assert trigger is not None
    assert trigger.kind == "path_b_trigger"
