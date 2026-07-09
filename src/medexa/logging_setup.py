from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    rid = str(uuid.uuid4())
    _request_id.set(rid)
    return rid


class _PhiFilter(logging.Filter):
    _PHI_KEYS = frozenset(
        {
            "patient_name",
            "first_name",
            "last_name",
            "dob",
            "date_of_birth",
            "ssn",
            "mrn",
            "address",
            "phone",
            "email",
            "zip",
            "diagnosis",
        }
    )

    def filter(self, record: logging.LogRecord) -> bool:
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            for key in self._PHI_KEYS:
                if key in extra:
                    extra[key] = "[REDACTED]"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _request_id.get(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())

    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(_PhiFilter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
