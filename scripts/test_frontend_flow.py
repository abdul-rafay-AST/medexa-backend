import urllib.request
import json

API = "http://127.0.0.1:8000"

data = json.dumps({"patient_id": "samuel-thompson", "therapist_id": "dr-sarah", "session_type": "Physical Therapy"}).encode()
req = urllib.request.Request(API + "/sessions/start", data=data, headers={"Content-Type": "application/json"})
resp = json.loads(urllib.request.urlopen(req).read())
print("=== START SESSION ===")
print(json.dumps(resp, indent=2))
sid = resp["session_id"]

chunk = json.dumps({"text": "soft tissue work on the right shoulder", "start_ts": 0.0, "end_ts": 3.5, "sequence": 1}).encode()
req2 = urllib.request.Request(API + "/sessions/" + sid + "/transcript-chunk", data=chunk, headers={"Content-Type": "application/json"})
resp2 = json.loads(urllib.request.urlopen(req2).read())
print("\n=== TRANSCRIPT CHUNK ===")
print("entities:", resp2["entities_detected"])
print("suggestions:", len(resp2["suggestions"]))
for s in resp2["suggestions"]:
    print("  ->", s["title"], " cpt:", s.get("cpt_code"), " region:", s.get("body_region"))
print("latency:", resp2["latency_ms"], "ms")

if resp2["suggestions"]:
    sug_id = resp2["suggestions"][0]["suggestion_id"]
    req3 = urllib.request.Request(API + "/sessions/" + sid + "/suggestions/" + sug_id + "/apply", data=b"", headers={"Content-Type": "application/json"}, method="POST")
    resp3 = json.loads(urllib.request.urlopen(req3).read())
    print("\n=== APPLY SUGGESTION ===")
    print("active_cpt:", resp3["active_cpt"])

req4 = urllib.request.Request(API + "/sessions/" + sid + "/insights")
resp4 = json.loads(urllib.request.urlopen(req4).read())
print("\n=== INSIGHTS ===")
if resp4.get("current_cpt"):
    cpt = resp4["current_cpt"]
    print("current CPT:", cpt["code"], "-", cpt["label"])
    print("timer:", cpt["duration_sec"], "s")

req5 = urllib.request.Request(API + "/sessions/" + sid + "/pause", data=b"", headers={"Content-Type": "application/json"}, method="POST")
resp5 = json.loads(urllib.request.urlopen(req5).read())
print("\n=== PAUSE ===")
print("status:", resp5["status"])

req6 = urllib.request.Request(API + "/sessions/" + sid + "/resume", data=b"", headers={"Content-Type": "application/json"}, method="POST")
resp6 = json.loads(urllib.request.urlopen(req6).read())
print("\n=== RESUME ===")
print("status:", resp6["status"], "active_cpt:", resp6["active_cpt"])

req7 = urllib.request.Request(API + "/sessions/" + sid + "/end", data=b"", headers={"Content-Type": "application/json"}, method="POST")
resp7 = json.loads(urllib.request.urlopen(req7).read())
print("\n=== END SESSION ===")
print(json.dumps(resp7, indent=2))
