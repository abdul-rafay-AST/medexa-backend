# Medexa MVP — Project Summary
**Generated:** June 23, 2026  
**Scope:** Backend architecture, plan compliance, bugs fixed, phases 3.5–5

---

## 1. What Is Medexa?

Real-time therapy session assistant for PT/OT clinicians. It:
- Listens to session audio → speech-to-text
- Detects clinical activities from transcript (rules-based, **no RAG/LLM** in live path)
- Maps activities → CPT billing codes via flat lookup files
- Tracks timed services, calculates units (CMS **8-minute rule**)
- Flags NCCI conflicts / Modifier 59 (advisory — **humans decide**)
- Powers live suggestions + right-panel insights (prototype screen 2)

**Target latency:** < 1 second from speech to alert on screen.

---

## 2. Golden Rules (Never Change)

| # | Rule |
|---|------|
| 1 | Live detection = **rules-based**, not AI. No RAG in real-time path. |
| 2 | Business logic = plain Python, testable locally. API/AWS are thin wrappers. |
| 3 | Rule files loaded **once** at startup into memory. |
| 4 | Live session state in **DynamoDB** in production (not Lambda memory). |
| 5 | System **flags**; clinicians **approve/reject**. |

---

## 3. Architecture (4 Layers)

```
Audio → Speech-to-Text → TranscriptChunk
  → EntityExtractor (synonyms + body regions)
  → CptLookupLoader (activity → CPT)
  → SuggestionGenerator (deduped inline cards)
  → BillingTimerEngine (track CPT time)
  → EightMinuteRuleCalculator (timed codes only)
  → NcciConflictChecker (conflict alerts)
  → InsightsBuilder (right panel JSON)
  → SessionStateRepository (in-memory local / DynamoDB cloud)
  → FastAPI + SSE → Frontend
```

---

## 4. Config Files (Flat Files)

| File | Size | Source | Purpose |
|------|------|--------|---------|
| `activity_synonyms.json` | Hundreds+ (curated) | You + LLM draft | Spoken phrase → activity_label |
| `body_regions.json` | Dozens | You + LLM draft | Phrase → normalized region |
| `cpt_lookup.json` | ~11–60 codes | AMA CPT (verified) | activity_label → CPT code |
| `cpt_metadata.json` | Per CPT | Verified table | timed/untimed, display names |
| `ncci_rules.json` | Thousands (prod) | **CMS NCCI PTP** (official) | Conflict pairs |

**Key:** Only NCCI needs official CMS import at scale. Synonyms grow iteratively; Comprehend Medical later replaces hand-enumeration.

**Vocabulary lock:** `activity_synonyms` values must match `cpt_lookup` keys (e.g. `manual_therapy`).

---

## 5. Verified CPT Map (11 codes)

| Activity | CPT | Timed? |
|----------|-----|--------|
| therapeutic_exercise | 97110 | Yes |
| neuromuscular_reeducation | 97112 | Yes |
| gait_training | 97116 | Yes |
| manual_therapy | 97140 | Yes |
| therapeutic_activity | 97530 | Yes |
| self_care_adl | 97535 | Yes |
| mechanical_traction | 97012 | No (1 unit/session) |
| electrical_stimulation | 97014 | No (Medicare: G0283) |
| ultrasound_therapy | 97035 | Yes |
| hot_cold_pack | 97010 | No |
| massage_therapy | 97124 | Yes (often bundles w/ 97140) |

---

## 6. Bugs Fixed

| Bug | Issue | Fix |
|-----|-------|-----|
| **A** | 8-min rule dropped units when remainders < 8 min each | Largest-remainder allocation without >=8 gate for table leftovers |
| **B** | NCCI `body_region_sensitive` always fired | Only conflict when same non-null body region |
| **C** | `is_billable` / `possible_cpt` never set | Wired `CptLookupLoader` into extractor |
| — | `"stop"` treated as clinical negation | Removed from negation regex (voice commands separate) |

---

## 7. Prototype ↔ Backend Mapping

| Prototype (Screen 2) | Backend |
|----------------------|---------|
| Live transcript | `POST /sessions/{id}/transcript-chunk` |
| Inline Apply cards | `SuggestionGenerator` + `POST .../suggestions/{id}/apply` |
| Current CPT + timer | `BillingTimerEngine` → `InsightsPanel.current_cpt` |
| Live extractions | `InsightsPanel.live_extractions` |
| 8-Min Rule panel | `EightMinuteRuleCalculator` (timed only) |
| Modifier 59 alert | `NcciConflictChecker` → `InsightsPanel.alerts` |
| Pause / Stop / Resume | `POST /pause`, `/resume`, `/end` |
| Voice "Hey Medexa" | **Frontend/edge** (not backend) — maps to REST endpoints |

---

## 8. Phase Status

| Phase | Goal | Status |
|-------|------|--------|
| 0–1 | Setup + schemas | ✅ Done |
| 2 | Loaders | ✅ Done |
| 3 | Core engine | ✅ Done |
| **3.5** | FastAPI + SSE + contract endpoints | ✅ **Fixed & complete (local)** |
| **4** | State persistence | ✅ In-memory + DynamoDB code (default: no AWS) |
| **5** | JSON logging + latency | ✅ Done |
| 6 | AWS Lambda + API Gateway | ❌ Not started |
| 7 | Polish + full test coverage | ⚠️ Partial |

**AWS account needed?** No for local dev. Only for DynamoDB *runtime* and Phase 6 deploy.

---

## 9. API Endpoints (Implemented)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/sessions/start` | Start session |
| GET | `/sessions` | List active sessions |
| POST | `/sessions/{id}/transcript-chunk` | Process speech text |
| GET | `/sessions/{id}/insights` | Right panel snapshot |
| GET | `/sessions/{id}/state` | Full session state |
| GET | `/sessions/{id}/suggestions` | All suggestion cards |
| GET | `/sessions/{id}/alerts` | All alerts |
| GET | `/sessions/{id}/billing-summary` | Post-session billing |
| GET | `/sessions/{id}/stream` | SSE real-time updates |
| POST | `/sessions/{id}/suggestions/{id}/apply` | Apply → start timer |
| POST | `/sessions/{id}/suggestions/{id}/dismiss` | Dismiss card |
| POST | `/sessions/{id}/timer/start|stop|switch` | Timer control |
| POST | `/sessions/{id}/pause|resume` | Voice-friendly pause |
| POST | `/sessions/{id}/alerts/{id}/approve|reject` | Human decision |
| POST | `/sessions/{id}/end` | End session |
| GET | `/health` | Health check |

---

## 10. Project Structure (Current)

```
medexa/
  config/                    # Flat rule files
  src/medexa/
    schemas.py                 # All Pydantic models
    config.py                  # Settings (use_dynamodb=False default)
    logging_setup.py           # Phase 5 JSON logs
    loaders/                   # Load-once JSON readers
    core/
      entity_extractor.py
      billing_timer_engine.py
      suggestion_generator.py
      eight_minute_rule.py
      ncci_conflict_checker.py
      insights_builder.py
      billing_summary_builder.py
      transcript_processor.py
    state/session_state_repository.py  # InMemory + DynamoDB
    api/server.py, sse.py, dependencies.py
  scripts/run_api_server.py
  scripts/run_local_session.py
  tests/                       # Unit tests per module
```

---

## 11. How to Run (No AWS)

```bash
pip install -e ".[dev]"
pytest -q
python scripts/run_local_session.py
python scripts/run_api_server.py   # → http://localhost:8000/docs
```

**Enable DynamoDB later:** `MEDEXA_USE_DYNAMODB=true` + AWS creds + table `medexa-sessions`.

---

## 12. Open Items / Next Steps

1. Run full `pytest` locally and confirm green.
2. Replace MVP NCCI (5 pairs) with official CMS import + versioning.
3. Expand `activity_synonyms.json` / `body_regions.json` (Prompts A & B).
4. Deploy to AWS Staging (Phase 6) for frontend Integration Checkpoints 2–4.
5. Voice wake-word layer on frontend ("Hey Medexa" → REST calls).
6. AWS Transcribe for audio (Comprehend Medical later for better entity extraction).
7. Post-session: SOAP notes / claim document (AI for documentation only).

---

## 13. Key Decisions

- **No RAG in live path** — deterministic rules only; RAG for documentation queries later.
- **Flat files in memory** — millisecond lookups; NCCI from CMS, not LLM-generated.
- **Voice commands** — client-side; backend exposes pause/resume/timer/session endpoints.
- **Untimed CPTs** — never through 8-minute rule; bill 1 unit per session.
- **Alert reconciliation** — clinician approve/reject persists across insight refreshes.

---

*End of summary*
