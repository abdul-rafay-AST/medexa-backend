from __future__ import annotations

from typing import Any

import pytest

from medexa.adapters.realtime.in_process_broker import InProcessBroker
from medexa.adapters.realtime.sse_adapter import SseRealtimeAdapter
from medexa.application.path_b_worker import PathBWorker
from medexa.config import MedexaConfig
from medexa.domain.events import PathBTriggerRequested
from medexa.schemas import PathBTriggerRecord, SessionState, TranscriptChunk
from medexa.state import InMemorySessionStateRepository
from medexa.utils.time import now_utc


class _FakeAssistant:
    def __init__(self, payloads: list[dict[str, Any]] | None = None) -> None:
        self._payloads = payloads or []
        self.calls = 0

    async def suggest(
        self,
        session_id: str,
        buffered_transcript: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self.calls += 1
        return self._payloads


@pytest.mark.asyncio
async def test_path_b_worker_skips_when_disabled() -> None:
    repo = InMemorySessionStateRepository()
    trigger_id = "t1"
    state = SessionState(
        session_id="s1",
        transcript_chunks=[
            TranscriptChunk(
                session_id="s1",
                chunk_id="c1",
                text="patient reports knee pain",
                start_ts=0,
                end_ts=15,
                sequence=0,
            )
        ],
        path_b_triggers=[
            PathBTriggerRecord(
                trigger_id=trigger_id,
                session_id="s1",
                reason="activity_changed",
                source_event_type="activity_changed",
            )
        ],
    )
    repo.save(state)

    settings = MedexaConfig(path_b_enabled=False)
    assistant = _FakeAssistant(
        [
            {
                "kind": "documentation_reminder",
                "title": "Pain scale",
                "body": "Document pain scale.",
                "confidence": "medium",
            }
        ]
    )
    broker = InProcessBroker()
    worker = PathBWorker(
        settings=settings,
        session_repo=repo,
        assistant=assistant,
        realtime=SseRealtimeAdapter(broker),
    )

    await worker.handle(
        PathBTriggerRequested(
            session_id="s1",
            trigger_id=trigger_id,
            reason="activity_changed",
            source_event_type="activity_changed",
        )
    )

    updated = repo.get("s1")
    assert updated is not None
    assert updated.path_b_triggers[0].status == "skipped"
    assert assistant.calls == 0
    assert updated.assistant_suggestions == []


@pytest.mark.asyncio
async def test_path_b_worker_persists_suggestions_without_mutating_billing() -> None:
    repo = InMemorySessionStateRepository()
    trigger_id = "t2"
    state = SessionState(
        session_id="s2",
        active_cpt="97110",
        transcript_chunks=[
            TranscriptChunk(
                session_id="s2",
                chunk_id="c1",
                text="therapeutic exercise for knee",
                start_ts=0,
                end_ts=15,
                sequence=0,
            )
        ],
        path_b_triggers=[
            PathBTriggerRecord(
                trigger_id=trigger_id,
                session_id="s2",
                reason="activity_changed",
                source_event_type="activity_changed",
            )
        ],
    )
    repo.save(state)
    before_segments = len(state.timer_segments)

    settings = MedexaConfig(path_b_enabled=True)
    assistant = _FakeAssistant(
        [
            {
                "suggestion_id": "as1",
                "kind": "missing_information",
                "title": "Pain scale",
                "body": "Consider documenting current pain level.",
                "confidence": "high",
            }
        ]
    )
    broker = InProcessBroker()
    realtime = SseRealtimeAdapter(broker)
    queue = broker.subscribe("s2")
    worker = PathBWorker(settings=settings, session_repo=repo, assistant=assistant, realtime=realtime)

    await worker.handle(
        PathBTriggerRequested(
            session_id="s2",
            trigger_id=trigger_id,
            reason="activity_changed",
            source_event_type="activity_changed",
        )
    )

    updated = repo.get("s2")
    assert updated is not None
    assert assistant.calls == 1
    assert updated.path_b_triggers[0].status == "completed"
    assert len(updated.assistant_suggestions) == 1
    assert updated.assistant_suggestions[0].title == "Pain scale"
    assert updated.active_cpt == "97110"
    assert len(updated.timer_segments) == before_segments

    event = await queue.get()
    assert event is not None
    assert event.kind == "assistant_suggestion"


@pytest.mark.asyncio
async def test_path_b_worker_retries_concurrent_save() -> None:
    class _FlakyRepo(InMemorySessionStateRepository):
        def __init__(self) -> None:
            super().__init__()
            self.failures_left = 2

        def save(self, state: SessionState) -> None:
            if self.failures_left > 0:
                self.failures_left -= 1
                raise RuntimeError(
                    f"Concurrent modification detected for session {state.session_id}"
                )
            super().save(state)

    repo = _FlakyRepo()
    trigger_id = "t3"
    state = SessionState(
        session_id="s3",
        transcript_chunks=[
            TranscriptChunk(
                session_id="s3",
                chunk_id="c1",
                text="patient reports knee pain 7/10",
                start_ts=0,
                end_ts=15,
                sequence=0,
            )
        ],
        path_b_triggers=[
            PathBTriggerRecord(
                trigger_id=trigger_id,
                session_id="s3",
                reason="pain_scale_mentioned",
                source_event_type="chunk_processed",
            )
        ],
    )
    InMemorySessionStateRepository.save(repo, state)
    repo.failures_left = 2

    settings = MedexaConfig(path_b_enabled=True)
    assistant = _FakeAssistant(
        [
            {
                "kind": "documentation_reminder",
                "title": "Document pain",
                "body": "Capture current pain score.",
                "confidence": "high",
            }
        ]
    )
    worker = PathBWorker(
        settings=settings,
        session_repo=repo,
        assistant=assistant,
        realtime=SseRealtimeAdapter(InProcessBroker()),
    )
    await worker.handle(
        PathBTriggerRequested(
            session_id="s3",
            trigger_id=trigger_id,
            reason="pain_scale_mentioned",
            source_event_type="chunk_processed",
        )
    )
    updated = repo.get("s3")
    assert updated is not None
    assert updated.path_b_triggers[0].status == "completed"
    assert len(updated.assistant_suggestions) == 1
