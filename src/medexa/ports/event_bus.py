from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from medexa.domain.events import DomainEvent

EventHandler = Callable[[DomainEvent], Awaitable[None] | None]


@runtime_checkable
class EventBusPort(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...

    def subscribe(self, event_type: str, handler: EventHandler) -> None: ...
