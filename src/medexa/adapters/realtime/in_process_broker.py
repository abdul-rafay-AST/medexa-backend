from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator

from medexa.domain.live_events import LiveEvent


class InProcessBroker:
    def __init__(self) -> None:
        self._channels: dict[str, list[asyncio.Queue[LiveEvent | None]]] = defaultdict(list)

    def subscribe(self, session_id: str) -> asyncio.Queue[LiveEvent | None]:
        queue: asyncio.Queue[LiveEvent | None] = asyncio.Queue()
        self._channels[session_id].append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[LiveEvent | None]) -> None:
        try:
            self._channels[session_id].remove(queue)
        except ValueError:
            return
        if not self._channels[session_id]:
            del self._channels[session_id]

    async def publish(self, session_id: str, event: LiveEvent) -> None:
        for queue in list(self._channels.get(session_id, [])):
            await queue.put(event)

    async def close_channel(self, session_id: str) -> None:
        for queue in list(self._channels.get(session_id, [])):
            await queue.put(None)
        self._channels.pop(session_id, None)

    @property
    def active_sessions(self) -> frozenset[str]:
        return frozenset(self._channels)


async def sse_encode_stream(session_id: str, broker: InProcessBroker) -> AsyncGenerator[str, None]:
    queue = broker.subscribe(session_id)
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {event.model_dump_json()}\n\n"
    finally:
        broker.unsubscribe(session_id, queue)
