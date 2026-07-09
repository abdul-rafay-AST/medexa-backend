from __future__ import annotations

from collections import defaultdict

from medexa.domain.events import DomainEvent
from medexa.ports.event_bus import EventHandler


class InProcessEventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        targets = list(self._handlers.get(event.event_type, []))
        targets.extend(self._handlers.get("*", []))
        for handler in targets:
            result = handler(event)
            if result is not None:
                await result
