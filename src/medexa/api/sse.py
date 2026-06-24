from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncGenerator

from medexa.schemas import InsightsPanel


class SSEBroker:
    def __init__(self) -> None:
        self._channels: dict[str, list[asyncio.Queue[InsightsPanel | None]]] = defaultdict(list)

    def subscribe(self, session_id: str) -> asyncio.Queue[InsightsPanel | None]:
        q: asyncio.Queue[InsightsPanel | None] = asyncio.Queue()
        self._channels[session_id].append(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue[InsightsPanel | None]) -> None:
        try:
            self._channels[session_id].remove(q)
        except ValueError:
            pass
        if not self._channels[session_id]:
            del self._channels[session_id]

    async def publish(self, session_id: str, panel: InsightsPanel) -> None:
        for q in self._channels.get(session_id, []):
            await q.put(panel)

    async def close_channel(self, session_id: str) -> None:
        for q in self._channels.get(session_id, []):
            await q.put(None)
        self._channels.pop(session_id, None)


sse_broker = SSEBroker()


async def sse_stream(session_id: str) -> AsyncGenerator[str, None]:
    q = sse_broker.subscribe(session_id)
    try:
        while True:
            panel = await q.get()
            if panel is None:
                break
            yield f"data: {panel.model_dump_json()}\n\n"
    finally:
        sse_broker.unsubscribe(session_id, q)
