# Medexa MVP — Implementation Plan

> **What is Medexa?**
> A real-time therapy session assistant. It listens to a therapy session, turns
> speech into text, spots clinical activities (like "manual therapy"), maps them
> to billing codes (CPT), tracks how long each activity is performed, calculates
> billing units using the **8-minute rule**, and flags billing conflicts (NCCI /
> Modifier 59) — all in near real time. It **assists** the clinician; it never
> makes the final billing decision.

---

## The golden rules (these never change)

1. **Real-time detection is rules-based, not AI.** The live path that detects
  CPT codes and conflicts uses simple, fast, in-memory rules. **No LLM, no RAG**
   in the live path. (AI can help *later* for summaries/documents only.)
2. **Business logic is plain Python, separate from AWS and APIs.** Every core piece runs
  and is tested **locally**. FastAPI and AWS handlers are thin wrappers added
   later to expose the logic.
3. **Load rule files once.** CPT/NCCI/region lookup tables are loaded into memory
  at startup — never re-read on every transcript chunk.
4. **Live state lives in DynamoDB.** Never rely on Lambda memory for session
  state (Lambda memory is temporary). Memory is only for the static rule files.
5. **The system flags, humans decide.** Every alert/suggestion is advisory and
  needs clinician/reviewer approval.

---

## Coding Standards & Best Practices

To ensure this MVP is robust and production-ready from day one, we will adhere to industry best practices:
- **Type Hinting & Pydantic:** Strict type hints across the entire codebase. Pydantic v2 for data validation at the boundaries.
- **Clean Architecture:** Core business logic will have zero dependencies on FastAPI, AWS, or databases. We will use interfaces (Protocols/ABCs) and Dependency Injection.
- **Single Responsibility Principle (SRP):** Each module does one thing (e.g., `ncci_conflict_checker.py` only checks conflicts, it doesn't parse text).
- **Comprehensive Testing:** Pytest for unit tests. We write tests alongside the logic, not as an afterthought.
- **Structured Logging:** JSON-based logging for easy CloudWatch ingestion.

---

## Frontend & Backend Integration Strategy (AWS First)

Since you are building the backend and another developer is building the frontend, we will integrate via an **AWS Staging Environment** from day one. We will bypass local tunneling tools (like ngrok) entirely and push our API directly to AWS for the frontend to consume.

### 1. The API Contract (OpenAPI/Swagger)
Because we are using **FastAPI** to define our routes, the backend will automatically generate an `openapi.json` file. 
- **What this means:** You don't need to write API docs manually. We generate the OpenAPI spec and provide it to the frontend developer so they know exactly what the endpoints are and what data they return.

### 2. Connecting the Environments (Staging Phase)
Instead of local tunnels, we will deploy our FastAPI app directly to AWS.
- **Solution:** We will use **AWS API Gateway + AWS Lambda** (using an adapter like Mangum for the FastAPI app) or **AWS App Runner** for the staging environment.
- The frontend developer will hit real AWS endpoints (e.g., `https://api.staging.medexa.com/...`) over the internet.
- This ensures that the frontend is always integrating with a production-like cloud environment, catching CORS, timeout, and infrastructure issues early.

### 3. Production Phase
When ready for production, we promote the exact same AWS infrastructure from Staging to Production, scaling up DynamoDB limits and Lambda concurrency as needed.

---

## Integration Checkpoints (When to sync with frontend)

To make sure the backend and frontend align perfectly with the prototype screens, we will integrate in these specific stages using the AWS Staging Environment:

### Checkpoint 1: The API Contract Sync (End of Phase 1)
- **Backend ready:** We have defined all Pydantic schemas (the exact JSON shapes).
- **Frontend action:** Frontend developer reviews the JSON shapes to ensure they have all the fields needed to render the "Dashboard" and "Live Session" UI. They can mock this data on their end.

### Checkpoint 2: The Static UI Hookup (AWS Staging - End of Phase 3.5)
- **Backend ready:** The FastAPI app is deployed to AWS (Staging) with "mock" endpoints that return hardcoded data conforming to the schemas.
- **Frontend action:** Connects their app to the **AWS Staging API URL**. Verifies that hitting `/sessions/start` works, and polling `/sessions/{id}/insights` populates the right panel (Current CPT, Extraction, 8-Min Rule, Alerts) with dummy data.

### Checkpoint 3: The Real-Time Live Session (AWS Staging - End of Phase 4)
- **Backend ready:** Core logic is hooked up. Transcript chunks can be sent, and the backend calculates units, generates alerts, and streams insights. Real DynamoDB tables are active in staging.
- **Frontend action:** Starts streaming real audio/text chunks to the AWS backend. Verifies that the UI updates in near real-time (< 1 second) as the therapist "speaks." Verifies the clinician can click "Apply" on a suggestion and see the timer start.

### Checkpoint 4: Post-Session & Billing (AWS Staging - End of Phase 4+)
- **Backend ready:** Endpoints for `/sessions/{id}/billing-summary` are active and deployed.
- **Frontend action:** Verifies the "Billing Intelligence" and "Claim Document" screens populate correctly when a session ends.

---

## How the live flow works (plain English)

```
Audio
  ->  Transcribe (speech-to-text)  ->  small text chunks
  ->  Entity Extractor (activities, body regions, timing, negation)
  ->  CPT Mapper (activity -> CPT code)
  ->  Suggestion Generator (inline Action + CPT cards for transcript)  <-- Includes Deduplication
  ->  Timer Engine (tracks active CPT time after clinician confirms)
  ->  8-Minute Rule (units + time-to-next-unit countdown)              <-- Uses largest remainder rule
  ->  NCCI Checker (flags conflicting CPT pairs on same body region)
  ->  Alert Generator (NCCI/conflict alerts for right panel)
  ->  Insights Builder (assembles full right-panel snapshot)
  ->  Save state to DynamoDB
  ->  Return to frontend via SSE stream
```

---

## Right-side insights panel (live dashboard)

Session-level summary that refreshes continuously.

### Insights API response bundle

```json
GET /sessions/{id}/insights

{
  "current_cpt": {
    "code": "97110",
    "label": "Therapeutic Exercise",
    "duration_sec": 742,
    "body_region": "shoulder_right",
    "billable": true,
    "status": "in_progress"
  },
  "live_extractions": [
    {"label": "Lower Back Stiffness", "duration_phrase": "2 weeks", "cpt": null},
    {"label": "Therapeutic Exercise", "body_region": "shoulder_right", "cpt": "97110"}
  ],
  "eight_minute_rule": {
    "total_minutes": 12,
    "total_units": 1,
    "seconds_to_next_unit": 898,
    "units_by_cpt": {"97110": 1, "97112": 0},
    "remainder_minutes": 4,
    "remainder_assigned_to": "97110"
  },
  "alerts": [
    {
      "alert_type": "ncci_conflict",
      "severity": "high",
      "message": "Potential conflict between 97110 and 97112...",
      "cpt_codes": ["97110", "97112"],
      "status": "open"
    }
  ],
  "session_timer_sec": 742
}
```

---

## Project structure (what we will build)

```
medexa/
  pyproject.toml
  README.md
  config/
    cpt_lookup.json
    ncci_rules.json
    body_regions.json
    activity_synonyms.json
  src/medexa/
    config.py                             # Settings via Pydantic Settings
    schemas.py                            # Data models
    logging_setup.py
    loaders/
      cpt_lookup_loader.py
      ncci_rules_loader.py
      body_region_normalizer.py
      activity_synonym_loader.py
    core/
      entity_extractor.py
      action_detector.py
      suggestion_generator.py             # With deduplication
      billing_timer_engine.py
      eight_minute_rule.py                # With largest-remainder rule
      unit_progress_calculator.py
      ncci_conflict_checker.py
      alert_generator.py
      insights_builder.py
      transcript_processor.py
    state/
      session_state_repository.py         # InMemory + DynamoDB (3 tables via Single Table Design)
    api/                                  # API server (Deployed to AWS)
      server.py                           # FastAPI routes
      dependencies.py                     # DI for repo, loaders
      sse.py                              # Server-Sent Events stream
    aws/
      lambda_handler.py
      transcribe_glue.py
  tests/
    test_entity_extractor.py
    test_cpt_mapping.py
    test_eight_minute_rule.py
    test_ncci_conflict_checker.py
    test_suggestion_generator.py
    test_insights_builder.py
    test_transcript_processor.py
    test_deduplication.py
  scripts/
    run_local_session.py                  # CLI demo
    run_api_server.py                     # uvicorn wrapper
```

---

## The Phases (Revised)

Each phase has: **Goal**, **What we build**, and **Done when**.
We build **bottom-up** so we always have something testable.

### Phase 0 — Project setup
**Goal:** A runnable Python project structure.
**Done when:** `pip install -e .` works and `pytest` runs.

### Phase 1 — Data shapes & rule files (the contracts)
**Goal:** Decide the exact shape of every piece of data.
**Done when:** Pydantic models import cleanly, sample JSON files are valid, and **Integration Checkpoint 1** is cleared.

### Phase 2 — Loaders
**Goal:** Fast, load-once access to all rule data.
**Done when:** Loaders return correct values and read files only once.

### Phase 3 — The brain (core engine)
**Goal:** All clinical/billing logic as pure, testable Python classes. No FastAPI or AWS yet.
**What we build:** Extractor, deduplication, CPT mapping, 8-minute rule (largest remainder), NCCI checker.
**Done when:** Core unit tests pass.

### Phase 3.5 — FastAPI Server (Staging Deployment)
**Goal:** Expose the engine via HTTP and SSE so the frontend can connect.
**Done when:** `run_api_server.py` starts the server, Swagger UI is visible, and **Integration Checkpoint 2** is cleared via the AWS Staging environment.

### Phase 4 — Saving state (Storage)
**Goal:** Persist session state.
**What we build:** InMemoryRepository, then DynamoDB tables (consolidated to 3 tables using single-table design patterns), handling concurrent session logic.
**Done when:** Engine reads/writes state correctly, and **Integration Checkpoint 3 & 4** are cleared.

### Phase 5 — Logging & latency
**Goal:** CloudWatch-ready; track speech-to-alert target.
**Done when:** Every processed chunk emits structured JSON logs.

### Phase 6 — AWS wrappers
**Goal:** Deploy to AWS API Gateway + Lambda.
**Done when:** Logic runs unchanged in the cloud.

### Phase 7 — Final Polish & Tests
**Goal:** Full confidence in billing logic.

---

## API Endpoints (FastAPI Contract)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/sessions/start` | Start session (with patient/therapist context) |
| POST | `/sessions/{id}/transcript-chunk` | Process chunk → suggestions + insights |
| GET | `/sessions/{id}/insights` | Right panel snapshot |
| GET | `/sessions/{id}/state` | Full session state |
| GET | `/sessions/{id}/suggestions` | All inline cards |
| GET | `/sessions/{id}/alerts` | All alerts |
| GET | `/sessions/{id}/stream` | **SSE stream for real-time updates** |
| GET | `/sessions/{id}/billing-summary` | Post-session billing review |
| GET | `/sessions` | Dashboard: list sessions |
| POST | `/sessions/{id}/suggestions/{sid}/apply` | Apply CPT suggestion |
| POST | `/sessions/{id}/suggestions/{sid}/set-duration` | Manual duration |
| POST | `/sessions/{id}/suggestions/{sid}/note-it` | Mark doc action |
| POST | `/sessions/{id}/suggestions/{sid}/dismiss` | Dismiss card |
| POST | `/sessions/{id}/timer/start` | Explicit timer start |
| POST | `/sessions/{id}/timer/stop` | Stop timer |
| POST | `/sessions/{id}/timer/switch` | Switch active CPT |
| POST | `/sessions/{id}/alerts/{aid}/approve` | Approve NCCI alert |
| POST | `/sessions/{id}/alerts/{aid}/reject` | Reject NCCI alert |
| POST | `/sessions/{id}/end` | End session |
