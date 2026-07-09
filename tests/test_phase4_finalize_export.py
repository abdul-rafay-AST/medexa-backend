from __future__ import annotations

from fastapi.testclient import TestClient

from medexa.api.server import app


def test_sa_finalize_session_exports_fhir_bundle() -> None:
    client = TestClient(app)
    started = client.post(
        "/sessions/start",
        json={
            "billingRegion": "SA",
            "payerId": "payer-1",
            "memberId": "member-1",
            "preAuthReference": "PA-999",
            "patientName": "Saudi Patient",
        },
    )
    assert started.status_code == 200
    session_id = started.json()["session"]["id"]

    finalized = client.post(
        f"/sessions/{session_id}/finalize-session",
        json={"transcript": "Therapy completed.", "totalSeconds": 1800},
    )
    assert finalized.status_code == 200
    body = finalized.json()
    assert body["fhirExport"] is not None
    assert body["fhirExport"]["profileId"] == "nphies-professional-claim"
    assert body["fhirExport"]["byteSize"] > 0
    assert body["preAuthReconciliation"]["reconciled"] is True


def test_us_finalize_session_skips_fhir_export() -> None:
    client = TestClient(app)
    started = client.post("/sessions/start", json={"patientName": "US Patient"})
    session_id = started.json()["session"]["id"]

    finalized = client.post(
        f"/sessions/{session_id}/finalize-session",
        json={"transcript": "US visit complete.", "totalSeconds": 900},
    )
    assert finalized.status_code == 200
    assert finalized.json()["fhirExport"] is None
