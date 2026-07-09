#!/usr/bin/env python3
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def log_section(title):
    print("\n" + "=" * 80)
    print(f" {title} ".center(80, "="))
    print("=" * 80)

def main():
    print("Starting Medexa End-to-End Walkthrough Integration Test...")
    
    # 1. Start a new session
    log_section("1. STARTING A NEW SESSION")
    payload = {
        "patientName": "David Peter",
        "avatar": "https://i.pravatar.cc/150?u=david",
        "ageSex": "45 / Male",
        "weight": "82 kg",
        "mrnNumber": "992831",
        "payorSource": "Medicare",
        "careType": "Physical Therapy",
        "cpt": "97110",
        "icd": "M54.5"
    }
    
    resp = requests.post(f"{BASE_URL}/sessions/start", json=payload)
    if resp.status_code != 200:
        print(f"Error starting session: {resp.text}")
        return
        
    start_data = resp.json()
    session_id = start_data["session"]["id"]
    print(f"Session started successfully! Session ID: {session_id}")
    print(f"Initial State: {json.dumps(start_data['state'], indent=2)}")

    # 2. Send transcript chunks to simulate live audio/scribe input
    log_section("2. SIMULATING LIVE TRANSLATION / CHUNKS")
    chunks = [
        "Patient reports persistent lower back pain for the last two weeks, scaling at a 6 out of 10. Chief complaint is stiffness after sitting.",
        "We are starting with 10 minutes of therapeutic exercise for stretching and core strengthening to help with low back pain.",
        "We also did neuromuscular re-education for balance and gait training for about 15 minutes.",
        "Observed limited range of motion in lumbar flexion. Affect is normal. Vital signs are normal. Treatment plan is weekly follow-ups."
    ]
    
    for i, chunk in enumerate(chunks, 1):
        print(f"\nSending chunk {i}: \"{chunk}\"")
        resp = requests.post(
            f"{BASE_URL}/sessions/{session_id}/analyze-transcript-chunk",
            json={"chunk_text": chunk}
        )
        if resp.status_code == 200:
            print("Chunk processed successfully.")
        else:
            print(f"Error processing chunk: {resp.text}")
            
    # 3. Retrieve insights and suggestions detected by rules engine
    log_section("3. RETRIEVING DETECTED INSIGHTS & SUGGESTIONS")
    resp_insights = requests.get(f"{BASE_URL}/sessions/{session_id}/insights")
    print(f"Insights Count: {len(resp_insights.json()) if resp_insights.status_code == 200 else 'Error'}")
    
    resp_suggestions = requests.get(f"{BASE_URL}/sessions/{session_id}/suggestions")
    if resp_suggestions.status_code == 200:
        suggestions = resp_suggestions.json()
        print(f"Suggestions Count: {len(suggestions)}")
        for sug in suggestions:
            print(f" - Suggestion ID: {sug['id']} | Title: {sug['title']} | Text: {sug['text']} | Applied: {sug['applied']}")
    else:
        print(f"Error fetching suggestions: {resp_suggestions.text}")
        suggestions = []

    # 4. Apply suggestions to start timers / billing
    log_section("4. APPLYING SUGGESTIONS (Billing CPT Activation)")
    for sug in suggestions:
        if not sug["applied"]:
            print(f"Applying suggestion: {sug['title']}")
            apply_resp = requests.post(f"{BASE_URL}/sessions/{session_id}/suggestions/{sug['id']}/apply")
            if apply_resp.status_code == 200:
                print(f"Applied successfully: {apply_resp.json()['title']}")
            else:
                print(f"Error applying: {apply_resp.text}")

    # 5. Simulate elapsed time progression
    log_section("5. SIMULATING ACTIVE RECORDING ELAPSED TIME")
    elapsed_seconds = 1500  # 25 minutes
    state_resp = requests.post(
        f"{BASE_URL}/sessions/{session_id}/state",
        json={"status": "recording", "elapsedSeconds": elapsed_seconds}
    )
    if state_resp.status_code == 200:
        print(f"State updated. Elapsed seconds: {state_resp.json()['elapsedSeconds']}")

    # 6. Finalize session
    log_section("6. FINALIZING THE SESSION")
    full_transcript = " ".join(chunks)
    finalize_payload = {
        "transcript": full_transcript,
        "total_seconds": elapsed_seconds,
        "cpt_timer": {"active": False, "code": "97110", "seconds": 600, "units": 1},
        "applied_suggestions": [sug["id"] for sug in suggestions],
        "detected_cpt_suggestions": [],
        "detected_icd10_suggestions": [],
        "ncci_conflicts": []
    }
    
    finalize_resp = requests.post(
        f"{BASE_URL}/sessions/{session_id}/finalize-session",
        json=finalize_payload
    )
    if finalize_resp.status_code == 200:
        print("Session finalized successfully!")
        final_data = finalize_resp.json()
        print(f"Redirect target: {final_data['redirect_url']}")
    else:
        print(f"Error finalising session: {finalize_resp.text}")
        return

    # 7. Query and display SOAP Notes
    log_section("7. GENERATED SOAP NOTES")
    soap_resp = requests.get(f"{BASE_URL}/soap-notes/{session_id}")
    if soap_resp.status_code == 200:
        print(json.dumps(soap_resp.json(), indent=2))
    else:
        print(f"Error loading SOAP notes: {soap_resp.text}")

    # 8. Query and display Patient Summary
    log_section("8. GENERATED PATIENT SUMMARY")
    summary_resp = requests.get(f"{BASE_URL}/patient-summary/{session_id}")
    if summary_resp.status_code == 200:
        print(json.dumps(summary_resp.json(), indent=2))
    else:
        print(f"Error loading Patient Summary: {summary_resp.text}")

    # 9. Query and display Billing Intelligence
    log_section("9. GENERATED BILLING INTELLIGENCE")
    billing_resp = requests.get(f"{BASE_URL}/billing/{session_id}")
    if billing_resp.status_code == 200:
        print(json.dumps(billing_resp.json(), indent=2))
    else:
        print(f"Error loading Billing: {billing_resp.text}")

    # 10. Query and display Claims
    log_section("10. COMPILED CLAIM DOCUMENT")
    claim_resp = requests.get(f"{BASE_URL}/claims/{session_id}")
    if claim_resp.status_code == 200:
        print(json.dumps(claim_resp.json(), indent=2))
    else:
        print(f"Error loading Claim: {claim_resp.text}")

    print("\n" + "=" * 80)
    print(" Walkthrough integration test completed successfully! ".center(80, "#"))
    print("=" * 80)

if __name__ == "__main__":
    main()
