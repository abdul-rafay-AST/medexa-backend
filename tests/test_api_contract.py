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
    assert body["session"]["billingRegion"] == "US"
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


def test_start_session_accepts_explicit_billing_region():
    resp = client.post(
        "/sessions/start",
        json={
            "patientName": "KSA Patient",
            "patientId": "patient-sa",
            "sessionType": "Physical Therapy",
            "billingRegion": "SA",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["session"]["billingRegion"] == "SA"


def test_start_session_accepts_future_gcc_fields():
    resp = client.post(
        "/sessions/start",
        json={
            "patientName": "Abu Dhabi Patient",
            "patientId": "patient-ae",
            "sessionType": "Physical Therapy",
            "billingRegion": "AE",
            "emirate": "DOH",
            "payerId": "payer-001",
            "memberId": "member-123",
            "preAuthReference": "auth-999",
        },
    )
    assert resp.status_code == 200
    session = resp.json()["session"]
    assert session["billingRegion"] == "AE"
    assert session["emirate"] == "DOH"
    assert session["payerId"] == "payer-001"
    assert session["memberId"] == "member-123"
    assert session["preAuthReference"] == "auth-999"


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

    suggestions = client.get(f"/sessions/{session_id}/suggestions").json()
    assert isinstance(suggestions, list)
    assert len(suggestions) >= 1


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


def test_timer_state_and_finalize_session():
    session_id = _start_session()

    timer = client.get(f"/sessions/{session_id}/timer-state").json()
    assert timer["session_id"] == session_id
    assert "cpt_timer" in timer

    started = client.post(f"/sessions/{session_id}/timer-state/start").json()
    assert started["recording_status"] == "recording"

    cpt = client.post(
        f"/sessions/{session_id}/cpt-timer/start",
        json={"code": "97110", "source": "manual", "reason": "Therapeutic exercise"},
    ).json()
    assert cpt["cpt_timer"]["code"] == "97110"

    client.post(
        f"/sessions/{session_id}/analyze-transcript-chunk",
        json={"chunk_text": "therapeutic exercise for shoulder pain"},
    )

    finalized = client.post(
        f"/sessions/{session_id}/finalize-session",
        json={
            "transcript": "Patient completed therapeutic exercise.",
            "total_seconds": 1200,
            "cpt_timer": {"active": False, "code": "97110", "seconds": 1200, "units": 1},
            "applied_suggestions": [],
            "detected_cpt_suggestions": [],
            "detected_icd10_suggestions": [],
            "ncci_conflicts": [],
        },
    ).json()
    assert finalized["sessionId"] == session_id
    assert finalized["soapNote"]["subjective"]["chiefComplaint"]
    assert finalized["redirectUrl"].startswith("/soap-notes")
