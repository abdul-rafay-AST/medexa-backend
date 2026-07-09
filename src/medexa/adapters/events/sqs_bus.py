from __future__ import annotations

from medexa.domain.events import DomainEvent


class SqsEventBus:
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError("SQS event bus is reserved for AWS production deployment")

    def subscribe(self, event_type: str, handler: object) -> None:
        raise NotImplementedError("SQS event bus is reserved for AWS production deployment")
