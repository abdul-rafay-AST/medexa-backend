from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_policy_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("records", [])
    if not isinstance(records, list):
        raise ValueError(f"Policy file {path} must contain a records array")
    return records


def load_policy_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"records": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_activity_synonyms(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    skip_keys = {
        "records",
        "source_name",
        "source_url",
        "version",
        "classification",
        "notes",
        "derived_from",
    }
    return {
        str(key).lower(): str(value)
        for key, value in raw.items()
        if not str(key).startswith("_") and key not in skip_keys
    }
