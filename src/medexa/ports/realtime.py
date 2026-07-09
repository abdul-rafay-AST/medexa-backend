from __future__ import annotations

from typing import Protocol, runtime_checkable

from medexa.domain.live_events import LiveEvent


@runtime_checkable
class RealtimePort(Protocol):
    async def publish(self, session_id: str, event: LiveEvent) -> None: ...
