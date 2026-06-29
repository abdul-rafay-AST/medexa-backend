# Medexa — Frontend ↔ Backend Integration Plan

> **Scope:** Connect [medexa-frontend](https://github.com/syedsaifshah786/medexa-frontend) to this backend using **rules-only / flat-file** detection. **No LLM. No voice wake-word.** The doctor **clicks a button** to start a session.

**Last updated:** June 2026

---

## 1. Can we integrate right now?

| Layer | Ready? | Notes |
|-------|--------|-------|
| **Backend API** | ✅ Yes | FastAPI running locally; all contract endpoints implemented |
| **Flat-file engine** | ✅ Yes | Synonyms, CPT, NCCI, 8-min rule, timers — no LLM |
| **Frontend UI** | ✅ Yes | Screens built (dashboard, live session, billing, claim) |
| **Frontend API wiring** | ❌ No | **All data is hardcoded mock** — zero `fetch` / SSE calls today |
| **AWS** | ❌ Not required | Integrate locally first: `localhost:8000` ↔ `localhost:3000` |

**Answer: Yes, you can start integration now** — but **the frontend repo needs an API client layer**. The backend does not need major changes for a first working demo.

---

## 2. What the frontend has today (audit)

Repo: `https://github.com/syedsaifshah786/medexa-frontend`

| Screen | Route | Data source today |
|--------|-------|-------------------|
| Dashboard / patient list | `/ambient-listening` | `src/lib/sessions.ts` — static array |
| Live session | `/ambient-listening/session` | Hardcoded `insights[]`, `suggestions[]`, local pause/stop state |
| Start session | `/start-session` | Redirects to live session — **no backend call** |
| Billing Intelligence | `/billing-intelligence` | Hardcoded `initialCptCodes[]` |
| SOAP Notes | `/soap-notes` | Static content |
| Patient Summary | `/patient-summary` | Static content |
| Claim Document | `/claim-document` | Static content |

**No `NEXT_PUBLIC_API_URL`, no `fetch`, no `EventSource` (SSE) anywhere in the repo.**

---

## 3. Confirmed product decisions (this integration)

| Decision | Choice |
|----------|--------|
| Live suggestions | **Flat-file rules** (`activity_synonyms.json` → `cpt_lookup.json`) |
| LLM (Haiku, etc.) | **Not in scope** |
| RAG | **Not in scope** |
| Session start | **Button click** on dashboard or patient card |
| Voice / "Hey Medexa" | **Removed** — use Pause / Resume / Stop **buttons** only |
| Speech-to-text | Frontend captures audio → sends **text chunks** to backend (AWS Transcribe later; browser STT OK for MVP demo) |

---

## 4. Architecture after integration

```
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND (Next.js, localhost:3000)                         │
│                                                             │
│  [Start Session button]                                     │
│       → POST /sessions/start                                │
│       → store session_id in React context / sessionStorage  │
│                                                             │
│  [Microphone / STT]                                         │
│       → POST /sessions/{id}/transcript-chunk  (text)        │
│                                                             │
│  [EventSource SSE]                                          │
│       → GET /sessions/{id}/stream  (live insights panel)    │
│                                                             │
│  [Apply suggestion]                                         │
│       → POST /sessions/{id}/suggestions/{sid}/apply       │
│                                                             │
│  [Pause / Resume / Stop buttons]                            │
│       → POST /pause | /resume | /end                        │
│                                                             │
│  [Billing screen after end]                                 │
│       → GET /sessions/{id}/billing-summary                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP + SSE
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  BACKEND (FastAPI, localhost:8000)                        │
│                                                             │
│  transcript_processor → entity_extractor → cpt_lookup     │
│  suggestion_generator → billing_timer_engine                │
│  eight_minute_rule + ncci_rules → insights_builder         │
│  InMemorySessionStateRepository (no AWS for local dev)      │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Local setup (both developers)

### Backend (this repo)

```bash
cd "Medexa Main"
pip install -e ".[dev]"
copy .env.example .env          # Windows
# Ensure: MEDEXA_CORS_ALLOW_ORIGINS=http://localhost:3000
python scripts/run_api_server.py
```

Verify: open **http://localhost:8000/docs** — Swagger UI should load.

### Frontend

```bash
git clone https://github.com/syedsaifshah786/medexa-frontend.git
cd medexa-frontend
npm install
```

Create `.env.local`:

```env
NEXT_PUBLIC_MEDEXA_API_URL=http://localhost:8000
```

```bash
npm run dev
```

Open **http://localhost:3000**

---

## 6. API contract — endpoint ↔ screen mapping

### Phase A — Session lifecycle (button start, no voice)

| User action | Frontend calls | Backend returns |
|-------------|----------------|-----------------|
| Click **Start Session** on patient card | `POST /sessions/start` | `{ session_id, status }` |
| Navigate to live session | Store `session_id` + patient display info locally | — |
| Open live session page | `GET /sessions/{id}/stream` (SSE connect) | Stream of `InsightsPanel` JSON |
| Click **Pause** | `POST /sessions/{id}/pause` | `{ status: "paused" }` |
| Click **Resume** | `POST /sessions/{id}/resume` | `{ status: "active" }` |
| Confirm **Stop** | `POST /sessions/{id}/end` | `{ total_minutes, total_units, units_by_cpt }` |

**Start session request body:**

```json
{
  "patient_id": "samuel-thompson",
  "therapist_id": "dr-sarah",
  "session_type": "Physical Therapy"
}
```

`patient_id` can be the frontend slug from `sessions.ts` (`"samuel-thompson"`). Patient name/MRN/avatar stay on the frontend for display — backend only needs the ID for now.

---

### Phase B — Live session (screen 2)

| UI area | Source | Endpoint |
|---------|--------|----------|
| Right panel — Current CPT | `insights.current_cpt` | SSE or `GET /insights` |
| Right panel — Live extractions | `insights.live_extractions` | SSE |
| Right panel — 8-Min Rule | `insights.eight_minute_rule` | SSE |
| Right panel — Alerts (Modifier 59) | `insights.alerts` | SSE |
| Suggestion cards (Apply) | `suggestions[]` from transcript response + `GET /suggestions` | `POST /transcript-chunk` |
| Session timer display | `insights.session_timer_sec` | SSE |
| Apply button | — | `POST /suggestions/{id}/apply` |
| Dismiss button | — | `POST /suggestions/{id}/dismiss` |
| Approve / Reject alert | — | `POST /alerts/{id}/approve` or `/reject` |

**Send transcript text (from STT or typed demo):**

```http
POST /sessions/{session_id}/transcript-chunk
Content-Type: application/json

{
  "text": "Let's do soft tissue work on the right shoulder",
  "start_ts": 0.0,
  "end_ts": 3.5,
  "sequence": 1
}
```

**Response (use immediately + SSE will also push `insights`):**

```json
{
  "chunk_id": "...",
  "entities_detected": 1,
  "suggestions": [
    {
      "suggestion_id": "...",
      "title": "Start billing Manual Therapy (97140)?",
      "message": "Detected 'soft tissue work' on shoulder_right — apply 97140?",
      "cpt_code": "97140",
      "body_region": "shoulder_right",
      "status": "suggested",
      "actions": [
        { "label": "Apply", "action_type": "apply" },
        { "label": "Dismiss", "action_type": "dismiss" }
      ]
    }
  ],
  "insights": { "...": "full InsightsPanel" },
  "latency_ms": 12
}
```

---

### Phase C — Post-session screens

| Screen | Endpoint | Maps to |
|--------|----------|---------|
| Billing Intelligence | `GET /sessions/{id}/billing-summary` | `total_units`, `line_items[]`, `eight_minute_rule`, `alerts` |
| Claim Document | Same billing summary + frontend ICD display | `line_items` for CPT table |
| SOAP Notes | **Not built on backend yet** | Keep frontend static until Phase 7+ |
| Patient Summary | **Not built on backend yet** | Keep frontend static until Phase 7+ |

---

## 7. Field mapping — frontend mock → backend JSON

### Suggestions panel (right side, live session)

| Frontend mock (`session/page.tsx`) | Backend `Suggestion` |
|-----------------------------------|----------------------|
| `item.title` | `suggestion.title` |
| `item.text` | `suggestion.message` |
| `item.id` | `suggestion.suggestion_id` |
| Apply button | `POST .../suggestions/{suggestion_id}/apply` |

### Alerts / Modifier 59

| Frontend mock | Backend `Alert` |
|---------------|-----------------|
| `"Modifier 59 Required"` title | `alert.message` (contains CPT pair + explanation) |
| `cpt_codes` | `alert.cpt_codes` |
| Approve / Reject | `POST .../alerts/{alert_id}/approve` or `/reject` |

### Billing Intelligence page

| Frontend `CptItem` | Backend `BillingLineItem` |
|--------------------|---------------------------|
| `code` | `cpt_code` |
| `title` | `display_name` |
| `units` | `units` (string → number) |
| `duration` | format `total_seconds` as `MM:SS` |
| `warning` / `note` | match from `alerts[]` where CPT in `cpt_codes` |

### Insights / “Protocol Ask” cards (left column)

The frontend mock mixes **protocol questions** and **billing** in one list. The backend today only returns **billing-related** extractions and alerts.

| MVP approach | Detail |
|--------------|--------|
| **Billing items** | Map from `insights.live_extractions` + `insights.alerts` |
| **Protocol Ask cards** | Keep as frontend-only OR hide until a future documentation feature exists |

Do not block integration on protocol cards — wire billing suggestions and alerts first.

---

## 8. Frontend files to create / change

### New files (recommended)

```
src/lib/api/
  client.ts          # base fetch wrapper (API_URL, error handling)
  sessions.ts          # start, end, pause, resume
  transcript.ts        # post transcript chunks
  insights.ts          # get insights, SSE hook
  suggestions.ts       # apply, dismiss
  alerts.ts            # approve, reject
  billing.ts           # billing-summary
  types.ts             # TypeScript types mirroring backend schemas

src/context/
  SessionContext.tsx   # holds backend session_id + patient display info
```

### Files to update

| File | Change |
|------|--------|
| `src/app/ambient-listening/page.tsx` | **Start Session** button → `POST /sessions/start` → navigate with `?backendSessionId=...` |
| `src/app/ambient-listening/session/page.tsx` | Replace mock arrays with API + SSE; wire Pause/Resume/Stop/Apply |
| `src/app/billing-intelligence/page.tsx` | Load from `GET /billing-summary` using stored `session_id` |
| `src/lib/sessions.ts` | Keep for **patient display metadata** (name, MRN, avatar); add `backendSessionId` separately |
| `.env.local` | `NEXT_PUBLIC_MEDEXA_API_URL=http://localhost:8000` |

### Remove / defer

| Item | Action |
|------|--------|
| Voice / "Hey Medexa" / "Say Stop Recording..." UI text | Remove or replace with button labels |
| `start-session/page.tsx` redirect-only | Update to call backend then redirect |

---

## 9. Backend changes needed (minimal)

The backend is **integration-ready** for rules-only MVP. Optional small improvements:

| Priority | Change | Why |
|----------|--------|-----|
| **Optional** | Extend `StartSessionRequest` with `patient_name`, `mrn` | Echo back in `GET /state` for debugging |
| **Optional** | `GET /sessions` returns ended sessions too (query param) | Dashboard "Recent Transactions" |
| **Later** | SOAP / patient summary endpoints | Screens 3–5 content generation |
| **Later** | AWS Transcribe webhook | Replace browser STT with server-side audio |
| **Not needed now** | LLM / Haiku | Explicitly out of scope |

**No backend change is blocking** the first end-to-end demo.

---

## 10. SSE integration pattern (frontend)

```typescript
// Pseudocode — use in live session page
const sessionId = sessionStorage.getItem("medexa_session_id");

useEffect(() => {
  const es = new EventSource(
    `${API_URL}/sessions/${sessionId}/stream`
  );

  es.onmessage = (event) => {
    const panel = JSON.parse(event.data); // InsightsPanel
    setCurrentCpt(panel.current_cpt);
    setExtractions(panel.live_extractions);
    setEightMinRule(panel.eight_minute_rule);
    setAlerts(panel.alerts);
    setTimerSec(panel.session_timer_sec);
  };

  return () => es.close();
}, [sessionId]);
```

Also call `POST /transcript-chunk` when STT produces text — the response includes fresh `suggestions` for the left/inline cards.

---

## 11. MVP demo flow (manual test script)

1. Start backend: `python scripts/run_api_server.py`
2. Start frontend: `npm run dev`
3. Open dashboard → pick **Samuel Thompson** → click **Start Session**
4. Frontend calls `POST /sessions/start` → saves `session_id`
5. Live session page opens SSE stream
6. **Demo without microphone:** add a temporary "Send test phrase" button that posts:
   - `"soft tissue work on the right shoulder"`
   - then `"therapeutic exercise on the right shoulder"`
7. Verify suggestion card appears → click **Apply**
8. Verify right panel shows `current_cpt: 97140`, timer ticking
9. Send second phrase → verify NCCI alert if both CPTs on same region
10. Click **Pause** → verify `POST /pause`, timer freezes in insights
11. Click **Resume** → verify timer restarts
12. Click **Stop** → `POST /end` → navigate to Billing Intelligence
13. Billing page loads `GET /billing-summary` → shows units + line items

---

## 12. Integration phases & owners

| Phase | Goal | Backend | Frontend | Done when |
|-------|------|---------|----------|-----------|
| **I-0** | Local env + CORS | Run server, `.env` CORS | `.env.local` API URL | `/health` returns ok from browser |
| **I-1** | Button start session | — | `POST /sessions/start` on button click | `session_id` stored, live page opens |
| **I-2** | SSE insights panel | — | `EventSource` on live page | Right panel updates from backend |
| **I-3** | Transcript + suggestions | — | `POST /transcript-chunk` (typed or STT) | Apply card appears for known phrases |
| **I-4** | Apply + timer | — | `POST .../apply` | Current CPT + timer in panel |
| **I-5** | Pause / Resume / Stop | — | Wire control buttons | Session ends, navigates to billing |
| **I-6** | Billing screen | — | `GET /billing-summary` | Units + CPT list from backend |
| **I-7** | Browser STT (optional) | — | Web Speech API → chunks | Speak phrase → suggestion appears |
| **I-8** | AWS staging deploy | Deploy API + CORS for staging URL | Point `NEXT_PUBLIC_MEDEXA_API_URL` to staging | Same flow on staging |

---

## 13. CORS & environment matrix

| Environment | Backend URL | Frontend URL | `MEDEXA_CORS_ALLOW_ORIGINS` |
|-------------|-------------|--------------|----------------------------|
| Local dev | `http://localhost:8000` | `http://localhost:3000` | `http://localhost:3000` |
| Staging | `https://api.staging.medexa.com` | `https://staging.medexa.com` | exact staging frontend origin |
| Production | `https://api.medexa.com` | `https://app.medexa.com` | exact production origin |

---

## 14. Known gaps (acceptable for MVP)

| Gap | Workaround |
|-----|------------|
| Frontend protocol/insight cards | Hide or keep static; backend only does billing |
| SOAP / Patient Summary | Static UI until post-session AI (later phase) |
| Dashboard "Recent Transactions" | Keep mock list; only live session uses API |
| Patient list not from backend | `sessions.ts` stays as schedule UI; backend gets `patient_id` on start |
| Speech-to-text | Typed test phrases or browser `webkitSpeechRecognition` for demo |
| DynamoDB | Use in-memory locally (`MEDEXA_USE_DYNAMODB=false`) |

---

## 15. Checklist before calling integration "done"

### Backend
- [ ] `python scripts/run_api_server.py` runs without errors
- [ ] `GET /health` → `{ "status": "ok" }`
- [ ] CORS allows `http://localhost:3000`
- [ ] `pytest` passes

### Frontend
- [ ] `NEXT_PUBLIC_MEDEXA_API_URL` set
- [ ] Start Session button creates backend session
- [ ] SSE connected on live page
- [ ] Transcript chunk produces suggestions for known phrases in `activity_synonyms.json`
- [ ] Apply starts timer; insights update
- [ ] Pause / Resume / Stop call correct endpoints
- [ ] Billing page reads `billing-summary` after end
- [ ] No voice activation UI in critical path

### Joint
- [ ] End-to-end demo completed (Section 11)
- [ ] Latency on transcript chunk < 1s (rules-only, local)

---

## 16. Quick reference — backend base URL

| Local | `http://localhost:8000` |
| Swagger | `http://localhost:8000/docs` |
| OpenAPI JSON | `http://localhost:8000/openapi.json` |

Share `openapi.json` with the frontend developer so they can generate TypeScript types (optional: `openapi-typescript`).

---

*Rules-only. No LLM. Button-started sessions. Integrate locally first, AWS staging second.*
