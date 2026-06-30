"""Integration tests for the frontend-facing API contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from medexa.api.server import app

client = TestClient(app)


def _start_session() -> str:
    resp = client.post(
        "/sessions/start",
        json={
            "patientName": "Jane Doe",
            "patientId": "patient-1",
            "sessionType": "Physical Therapy",
            "mrnNumber": "MRN-001",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "session" in body and "state" in body
    assert body["session"]["patientName"] == "Jane Doe"
    assert body["state"]["status"] == "recording"
    return body["session"]["id"]


def test_health_and_session_lifecycle():
    assert client.get("/health").json() == {"status": "ok"}
    session_id = _start_session()

    sessions = client.get("/sessions").json()
    assert any(s["id"] == session_id for s in sessions)

    state = client.get(f"/sessions/{session_id}/state").json()
    assert state["status"] == "recording"

    paused = client.post(
        f"/sessions/{session_id}/state",
        json={"status": "paused", "elapsedSeconds": 120},
    ).json()
    assert paused["status"] == "paused"
    assert paused["elapsedSeconds"] == 120


def test_analyze_transcript_chunk_returns_clinical_analysis():
    session_id = _start_session()
    resp = client.post(
        f"/sessions/{session_id}/analyze-transcript-chunk",
        json={
            "chunk_text": "Patient reports low back pain. We did soft tissue work on the right shoulder.",
            "start_time": "0:00",
            "end_time": "0:15",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "possible_diagnoses" in body
    assert "icd10_suggestions" in body
    assert "cpt_suggestions" in body
    assert "soap_update" in body
    assert body["disclaimer"]

    insights = client.get(f"/sessions/{session_id}/insights").json()
    assert isinstance(insights, list)
    assert len(insights) >= 1


def test_documentation_billing_and_claims_endpoints():
    session_id = _start_session()
    client.post(
        f"/sessions/{session_id}/analyze-transcript-chunk",
        json={"chunk_text": "therapeutic exercise for knee pain"},
    )

    soap = client.post(f"/soap-notes/{session_id}/generate").json()
    assert "subjective" in soap
    assert soap["subjective"]["chiefComplaint"]

    summary = client.post(f"/patient-summary/{session_id}/send").json()
    assert summary["sent"] is True
    assert summary["summary"]

    billing = client.get(f"/billing/{session_id}").json()
    assert "cptCodes" in billing
    assert "snfFunctionalLogic" in billing

    claim = client.get(f"/claims/{session_id}").json()
    assert "patientMeta" in claim
    assert claim["claimStatus"] == "draft"

    verified = client.post(f"/claims/{session_id}/verify").json()
    assert verified["claimStatus"] == "verified"


def test_legacy_transcript_chunk_still_works():
    session_id = _start_session()
    resp = client.post(
        f"/sessions/{session_id}/transcript-chunk",
        json={"text": "soft tissue work on the right shoulder", "start_ts": 0.0, "end_ts": 3.0, "sequence": 1},
    )
    assert resp.status_code == 200
    assert resp.json()["entities_detected"] >= 1
