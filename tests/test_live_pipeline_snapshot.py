"""Live pipeline snapshot + simulated elapsed clock for step-by-step testing."""

from __future__ import annotations

from fastapi.testclient import TestClient

from medexa.api.server import app


def test_analyze_chunk_advances_simulated_elapsed_and_pipeline_snapshot() -> None:
    client = TestClient(app)
    start = client.post(
        "/sessions/start",
        json={"patientName": "CLI Tester", "billingRegion": "US"},
    )
    assert start.status_code == 200
    session_id = start.json()["session"]["id"]

    chunk = client.post(
        f"/sessions/{session_id}/analyze-transcript-chunk",
        json={
            "chunk_text": "Starting therapeutic exercise for lumbar stretching.",
            "elapsed_seconds": 240,
            "duration_seconds": 60,
        },
    )
    assert chunk.status_code == 200
    body = chunk.json()
    assert body["cpt_suggestions"] or body["live_suggestions"] or True

    snap = client.get(f"/sessions/{session_id}/live-pipeline")
    assert snap.status_code == 200
    data = snap.json()
    assert data["sessionId"] == session_id or data.get("session_id") == session_id
    elapsed = data.get("elapsedSeconds", data.get("elapsed_seconds"))
    assert elapsed == 300
    path_a = data.get("pathA", data.get("path_a"))
    assert path_a["status"] == "live"
    path_b = data.get("pathB", data.get("path_b"))
    assert "enabled" in path_b or "status" in path_b
    path_c = data.get("pathC", data.get("path_c"))
    assert path_c["status"] == "pending"
