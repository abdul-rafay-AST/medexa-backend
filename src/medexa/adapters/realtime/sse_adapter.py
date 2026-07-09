from __future__ import annotations

from medexa.adapters.realtime.in_process_broker import InProcessBroker
from medexa.domain.live_events import LiveEvent


class SseRealtimeAdapter:
    def __init__(self, broker: InProcessBroker) -> None:
        self._broker = broker

    async def publish(self, session_id: str, event: LiveEvent) -> None:
        await self._broker.publish(session_id, event)

    @property
    def broker(self) -> InProcessBroker:
        return self._broker
