"""Disk-backed session store — survives HF Space worker restarts within the same container."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from medexa.schemas import SessionState

logger = logging.getLogger(__name__)


class FileSessionStateRepository:
    """JSON file per session — default for Docker/HF when DynamoDB is disabled."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._directory.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, SessionState] = {}

    def _path(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_")
        return self._directory / f"{safe}.json"

    def get(self, session_id: str) -> SessionState | None:
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached.model_copy(deep=True)

        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            state = SessionState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            logger.warning("session_file_read_failed", extra={"extra_fields": {"session_id": session_id}})
            return None
        self._cache[session_id] = state
        return state.model_copy(deep=True)

    def save(self, state: SessionState) -> None:
        copy = state.model_copy(deep=True)
        self._cache[state.session_id] = copy
        path = self._path(state.session_id)
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(copy.model_dump_json(), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            logger.warning("session_file_write_failed", extra={"extra_fields": {"session_id": state.session_id}})

    def delete(self, session_id: str) -> None:
        self._cache.pop(session_id, None)
        path = self._path(session_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("session_file_delete_failed", extra={"extra_fields": {"session_id": session_id}})

    def list_active(self) -> list[SessionState]:
        return [state for state in self.list_all() if state.status == "active"]

    def list_all(self) -> list[SessionState]:
        results: list[SessionState] = []
        for path in self._directory.glob("*.json"):
            if path.suffix == ".tmp" or path.name.endswith(".json.tmp"):
                continue
            try:
                state = SessionState.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            self._cache[state.session_id] = state
            results.append(state.model_copy(deep=True))
        return results
