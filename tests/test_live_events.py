from __future__ import annotations

import pytest

from medexa.adapters.realtime.in_process_broker import InProcessBroker
from medexa.domain.live_events import LiveEvent, LiveEventFactory
from medexa.schemas import InsightsPanel


@pytest.mark.asyncio
async def test_broker_publishes_live_events_to_subscribers():
    broker = InProcessBroker()
    queue = broker.subscribe("s1")
    panel = InsightsPanel(session_id="s1", session_timer_sec=120)
    event = LiveEventFactory.path_a_snapshot("s1", panel, event_id="e1")
    await broker.publish("s1", event)
    received = await queue.get()
    assert isinstance(received, LiveEvent)
    assert received.kind == "path_a_snapshot"
    assert received.payload["panel"]["session_timer_sec"] == 120


@pytest.mark.asyncio
async def test_broker_close_channel_sends_sentinel():
    broker = InProcessBroker()
    queue = broker.subscribe("s1")
    await broker.close_channel("s1")
    assert await queue.get() is None
