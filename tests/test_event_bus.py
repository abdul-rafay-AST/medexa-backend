from __future__ import annotations

import pytest

from medexa.adapters.events.in_process_bus import InProcessEventBus
from medexa.domain.events import ActivityChanged, ChunkProcessed


@pytest.mark.asyncio
async def test_event_bus_delivers_typed_and_wildcard_handlers():
    bus = InProcessEventBus()
    received: list[str] = []

    async def on_activity(event: object) -> None:
        received.append(f"activity:{getattr(event, 'activity_label', '')}")

    async def on_any(event: object) -> None:
        received.append(f"any:{getattr(event, 'event_type', '')}")

    bus.subscribe("activity_changed", on_activity)
    bus.subscribe("*", on_any)

    await bus.publish(
        ActivityChanged(
            session_id="s1",
            activity_label="manual_therapy",
            cpt_code="97140",
            body_region="back",
        )
    )
    assert received == ["activity:manual_therapy", "any:activity_changed"]


@pytest.mark.asyncio
async def test_event_bus_chunk_processed_only_wildcard():
    bus = InProcessEventBus()
    received: list[str] = []

    async def on_activity(event: object) -> None:
        received.append("activity")

    async def on_any(event: object) -> None:
        received.append("wildcard")

    bus.subscribe("activity_changed", on_activity)
    bus.subscribe("*", on_any)

    await bus.publish(
        ChunkProcessed(
            session_id="s1",
            chunk_id="c1",
            sequence=0,
            entity_count=0,
            suggestion_count=0,
        )
    )
    assert received == ["wildcard"]
