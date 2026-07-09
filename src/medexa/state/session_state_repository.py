from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from medexa.schemas import SessionState


@runtime_checkable
class SessionStateRepository(Protocol):
    """Storage interface for session state. The engine depends only on this
    Protocol, so in-memory (local) and DynamoDB (cloud) are interchangeable."""

    def get(self, session_id: str) -> SessionState | None: ...
    def save(self, state: SessionState) -> None: ...
    def delete(self, session_id: str) -> None: ...
    def list_active(self) -> list[SessionState]: ...
    def list_all(self) -> list[SessionState]: ...


class InMemorySessionStateRepository:
    """Local, dependency-free repository. Requires NO AWS account.

    Note: Lambda memory is ephemeral, so this is for local dev/tests only.
    Production live state must use DynamoDB (golden rule #4)."""

    def __init__(self) -> None:
        self._store: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState | None:
        return self._store.get(session_id)

    def save(self, state: SessionState) -> None:
        # Store a copy so external mutations don't leak into the store implicitly.
        self._store[state.session_id] = state.model_copy(deep=True)

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def list_active(self) -> list[SessionState]:
        return [s.model_copy(deep=True) for s in self._store.values() if s.status == "active"]

    def list_all(self) -> list[SessionState]:
        return [s.model_copy(deep=True) for s in self._store.values()]


class DynamoDbSessionStateRepository:
    """DynamoDB-backed repository (single-table design).

    The full SessionState is serialized to JSON under the ``state`` attribute,
    keyed by ``session_id`` (partition key). ``status`` is duplicated as a
    top-level attribute so ``list_active`` can filter without deserializing all.

    Table (create once in AWS):
        partition key: session_id (S)
    Requires AWS credentials/region to actually run; importing this module does not.
    """

    def __init__(self, table_name: str, region_name: str | None = None) -> None:
        import boto3  # imported lazily so local/in-memory use needs no AWS SDK setup

        self._dynamodb = boto3.resource("dynamodb", region_name=region_name)
        self._table = self._dynamodb.Table(table_name)

    def get(self, session_id: str) -> SessionState | None:
        response = self._table.get_item(Key={"session_id": session_id})
        item = response.get("Item")
        if not item:
            return None
        return SessionState.model_validate_json(item["state"])

    def save(self, state: SessionState) -> None:
        import time

        ttl_seconds = 7 * 24 * 60 * 60
        self._table.put_item(
            Item={
                "session_id": state.session_id,
                "status": state.status,
                "billing_region": state.billing_region,
                "state": state.model_dump_json(),
                "ttl": int(time.time()) + ttl_seconds,
            }
        )

    def delete(self, session_id: str) -> None:
        self._table.delete_item(Key={"session_id": session_id})

    def list_active(self) -> list[SessionState]:
        from boto3.dynamodb.conditions import Attr

        results: list[SessionState] = []
        scan_kwargs = {"FilterExpression": Attr("status").eq("active")}
        while True:
            response = self._table.scan(**scan_kwargs)
            for item in response.get("Items", []):
                results.append(SessionState.model_validate_json(item["state"]))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
        return results

    def list_all(self) -> list[SessionState]:
        results: list[SessionState] = []
        scan_kwargs: dict[str, Any] = {}
        while True:
            response = self._table.scan(**scan_kwargs)
            for item in response.get("Items", []):
                results.append(SessionState.model_validate_json(item["state"]))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
        return results
