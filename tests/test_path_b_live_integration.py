from __future__ import annotations

import time

from fastapi.testclient import TestClient

from medexa.api.server import app


def test_path_b_trigger_survives_chunk_save() -> None:
    """Path B worker updates must not be overwritten by analyze-transcript-chunk save."""
    client = TestClient(app)

    started = client.post(
        "/sessions/start",
        json={"patientName": "Test", "patientId": "p1", "sessionType": "PT"},
    )
    assert started.status_code == 200
    session_id = started.json()["session"]["id"]

    chunk = client.post(
        f"/sessions/{session_id}/analyze-transcript-chunk",
        json={
            "chunk_text": (
                "Patient reports shoulder pain 7 out of 10. "
                "Starting manual therapy and therapeutic exercise."
            ),
            "elapsed_seconds": 0,
            "duration_seconds": 15,
        },
    )
    assert chunk.status_code == 200

    # Allow background Path B (Bedrock) to finish when configured.
    time.sleep(12)

    pipeline = client.get(f"/sessions/{session_id}/live-pipeline").json()
    path_b = pipeline.get("pathB", pipeline.get("path_b", {}))
    triggers = path_b.get("triggers", [])
    assert triggers, "expected at least one Path B trigger"
    assert triggers[-1]["status"] in {"dispatched", "completed", "skipped"}

    suggestions = client.get(f"/sessions/{session_id}/assistant-suggestions").json()
    if path_b.get("enabled") and triggers[-1]["status"] == "completed":
        assert len(suggestions) >= 1
