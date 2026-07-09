from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from medexa.domain.assistant_suggestion import AssistantSuggestion
from medexa.schemas import Alert, InsightsPanel, PathBTriggerRecord
from medexa.utils.time import now_utc


class LiveEvent(BaseModel):
    session_id: str
    event_id: str
    occurred_at: datetime = Field(default_factory=now_utc)
    kind: Literal[
        "path_a_snapshot",
        "alert",
        "timer_update",
        "path_b_trigger",
        "domain_event",
        "pre_auth_warning",
        "billing_conflict",
        "assistant_suggestion",
    ]
    payload: dict[str, Any]

    model_config = {"frozen": True}


class LiveEventFactory:
    @staticmethod
    def path_a_snapshot(session_id: str, panel: InsightsPanel, *, event_id: str) -> LiveEvent:
        return LiveEvent(
            session_id=session_id,
            event_id=event_id,
            kind="path_a_snapshot",
            payload={"panel": panel.model_dump(mode="json")},
        )

    @staticmethod
    def timer_update(
        session_id: str,
        *,
        event_id: str,
        session_timer_sec: int,
        active_cpt: str | None,
    ) -> LiveEvent:
        return LiveEvent(
            session_id=session_id,
            event_id=event_id,
            kind="timer_update",
            payload={
                "session_timer_sec": session_timer_sec,
                "active_cpt": active_cpt,
            },
        )

    @staticmethod
    def alert(session_id: str, alert: Alert, *, event_id: str) -> LiveEvent:
        return LiveEvent(
            session_id=session_id,
            event_id=event_id,
            kind="alert",
            payload={"alert": alert.model_dump(mode="json")},
        )

    @staticmethod
    def path_b_trigger(session_id: str, record: PathBTriggerRecord, *, event_id: str) -> LiveEvent:
        return LiveEvent(
            session_id=session_id,
            event_id=event_id,
            kind="path_b_trigger",
            payload={"trigger": record.model_dump(mode="json")},
        )

    @staticmethod
    def pre_auth_warning(session_id: str, alert: Alert, *, event_id: str) -> LiveEvent:
        return LiveEvent(
            session_id=session_id,
            event_id=event_id,
            kind="pre_auth_warning",
            payload={"alert": alert.model_dump(mode="json")},
        )

    @staticmethod
    def billing_conflict(session_id: str, alert: Alert, *, event_id: str) -> LiveEvent:
        return LiveEvent(
            session_id=session_id,
            event_id=event_id,
            kind="billing_conflict",
            payload={"alert": alert.model_dump(mode="json")},
        )

    @staticmethod
    def assistant_suggestion(
        session_id: str,
        suggestion: AssistantSuggestion,
        *,
        event_id: str,
    ) -> LiveEvent:
        return LiveEvent(
            session_id=session_id,
            event_id=event_id,
            kind="assistant_suggestion",
            payload={"suggestion": suggestion.model_dump(mode="json")},
        )

    @staticmethod
    def domain_event(session_id: str, event_type: str, data: dict[str, Any], *, event_id: str) -> LiveEvent:
        return LiveEvent(
            session_id=session_id,
            event_id=event_id,
            kind="domain_event",
            payload={"event_type": event_type, "data": data},
        )
