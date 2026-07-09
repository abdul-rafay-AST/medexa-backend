"""Quick API test for insight approve flow."""
import json
import httpx

base = "http://localhost:8000"
client = httpx.Client(timeout=30.0)

r = client.post(f"{base}/sessions/start", json={"patientName": "Test Patient"})
r.raise_for_status()
sid = r.json()["session"]["id"]

client.post(
    f"{base}/sessions/{sid}/analyze-transcript-chunk",
    json={"chunk_text": "therapeutic exercise for lumbar spine range of motion gait training"},
).raise_for_status()

insights = client.get(f"{base}/sessions/{sid}/insights").json()
print("INSIGHTS:", json.dumps(insights, indent=2))

for ins in insights:
    if ins.get("type") in ("detected", "billing") and ins.get("status") == "pending":
        iid = ins["id"]
        ar = client.post(f"{base}/sessions/{sid}/insights/{iid}/approve")
        print(f"APPROVE {iid}: {ar.status_code} {ar.text[:300]}")
