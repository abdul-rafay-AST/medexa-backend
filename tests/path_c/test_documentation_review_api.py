from __future__ import annotations

from fastapi.testclient import TestClient

from medexa.api.server import app


def test_finalize_returns_documentation_review_summary() -> None:
    client = TestClient(app)
    started = client.post("/sessions/start", json={"patientName": "Review Patient"})
    session_id = started.json()["session"]["id"]

    finalized = client.post(
        f"/sessions/{session_id}/finalize-session",
        json={"transcript": "Therapy session with knee exercises.", "totalSeconds": 900},
    )
    assert finalized.status_code == 200
    body = finalized.json()
    assert body["documentationReview"] is not None
    assert "openCount" in body["documentationReview"]


def test_documentation_review_endpoint() -> None:
    client = TestClient(app)
    started = client.post("/sessions/start", json={"patientName": "Checklist Patient"})
    session_id = started.json()["session"]["id"]
    client.post(
        f"/sessions/{session_id}/finalize-session",
        json={"transcript": "Session notes.", "totalSeconds": 600},
    )

    review = client.get(f"/sessions/{session_id}/documentation-review")
    assert review.status_code == 200
    payload = review.json()
    assert payload["sessionId"] == session_id
    assert "items" in payload
