# Medexa Simulator Walkthrough — Short PT Session Script

**Use with:** Session page → `?simulator=true` → Chat Simulator  
**Region:** US (NCCI + 8-minute rule enabled)  
**Goal:** See Path A entities, billing suggestions, NCCI conflicts, Path B clinical hints, and unit timer behavior in the right order.

---

## Quick reference — two clocks

| Clock | What it measures | Where you see it |
|-------|------------------|------------------|
| **Session timer** | Real wall-clock time since Start | Large timer (top card) |
| **Billing timer** | Seconds on an **applied** CPT segment only | Right card: `MM:SS billed · + MM:SS left` |

**Rule:** Sending chat lines advances the session timer. The billing timer **only** moves after you **Apply** a CPT suggestion and the session is **running**.

**8-minute rule (US):** 1 unit = 8 minutes of **timed** CPT work. `+ MM:SS left` counts down billing seconds until the next unit.

---

## Before you start

1. Dashboard → **Start a new session** (US billing).
2. Open session with **`?simulator=true`**.
3. Tap **Start** on the bottom bar (session must be running).
4. Keep the right column visible: **Suggestions** (top) + **Clinical Entities** (bottom).

---

## The conversation (send one line at a time)

Send as **Patient** or **Therapist** exactly as labeled. **Wait** where indicated before sending the next line.

---

### Step 1 — Clinical context only (no CPT yet)

**Speaker:** Patient  
**Send:**
> My lower back has been hurting for two weeks. Pain is about 6 out of 10 today. It gets worse when I bend forward.

| Action | Wait |
|--------|------|
| Send line | **~3–5 sec** — let Path A + Path B poll |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Session timer | Jumps to real send time (e.g. `00:05`) |
| Billing timer | **Stays `00:00`** — no CPT applied yet |
| Entities sidebar | Symptoms / body region (lumbar, pain) may appear |
| Billing suggestions | **None** (no billable procedure named) |
| Clinical tab (Path B) | May get a hint — trigger reason `clinical_context` (headaches/pain/history keywords, no CPT) |
| Alerts | **None** |

**Do not** apply anything yet.

---

### Step 2 — First CPT: Therapeutic Exercise (97110)

**Speaker:** Therapist  
**Send:**
> Understood. Let's start therapeutic exercise for lumbar stretching and core strengthening.

| Action | Wait |
|--------|------|
| Send line | **~2 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Entities sidebar | `therapeutic exercise` / lumbar — **Billable** |
| Billing suggestions | **One** card: *Start billing Therapeutic Exercise (97110)?* |
| Dedup check | Only **one** suggestion for 97110 (not a duplicate) |

**Now — Apply 97110**

| Action | Wait |
|--------|------|
| Click **Apply** on the 97110 suggestion | **~2 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Billing timer | **Starts counting** (e.g. `00:03 billed`) |
| Session timer | Keeps ticking independently |
| Unit display | `Unit 1 at 08:00` · `+ ~07:57 left` (based on billing seconds) |
| Applied card | Moves to “Unit Recorded” style in suggestions |

---

### Step 3 — Repeat same CPT (dedup test)

**Speaker:** Therapist  
**Send:**
> We'll continue therapeutic exercise with a resistance band for about ten minutes.

| Action | Wait |
|--------|------|
| Send line | **~2 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Billing suggestions | **No second 97110 card** — already suggested/applied |
| Entities sidebar | May show another entity line for this chunk |
| Billing timer | **Keeps running** on active 97110 segment |

**Optional:** If you had **Dismissed** 97110 earlier instead of applying, a **new** 97110 suggestion would be allowed. Applied/suggested blocks permanently.

---

### Step 4 — Pause, then check timers

| Action | Wait |
|--------|------|
| Tap **Pause** on bottom bar | **~5 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Session timer | **Stops** |
| Billing timer | **Stops** (CPT segment paused) |

Resume when ready for the next block.

---

### Step 5 — Neuromuscular re-education (97112) — no conflict yet

**Speaker:** Patient  
**Send:**
> Balance feels off when I turn quickly.

| Action | Wait |
|--------|------|
| Send (after **Resume**) | **~3 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Clinical tab | Path B may fire again (balance / symptom language) |
| Billing | No new CPT from patient line alone |

**Speaker:** Therapist  
**Send:**
> Next is neuromuscular re-education for balance and gait training.

| Action | Wait |
|--------|------|
| Send line | **~2 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Billing suggestions | New card: **97112** (Neuromuscular Re-education) |
| NCCI on suggestion text | May show `[NCCI warning vs 97110: ...]` because 97110 is **already active** |

**Apply 97112** — this is the conflict step.

| Action | Wait |
|--------|------|
| Click **Apply** on 97112 | **~2 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Alerts / insights | **NCCI conflict** warning: `97110` + `97112` (or `97140` if you add manual therapy next) |
| Message | Mentions **Modifier 59** if applicable |
| Billing timer | Switches to **97112** segment; 97110 segment stops |
| Apply still succeeds | Conflict is a **warning**, not a hard block |

---

### Step 6 — Manual therapy (97140) — stronger NCCI pair

**Speaker:** Therapist  
**Send:**
> I'll finish with manual therapy soft tissue mobilization on the lumbar spine.

| Action | Wait |
|--------|------|
| Send line | **~2 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Billing suggestions | **97140** (Manual Therapy) |
| Suggestion message | NCCI pre-warning if another timed CPT is active |

**Apply 97140**

| Action | Wait |
|--------|------|
| Click **Apply** | **~2 sec** |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| NCCI alert | **97140 + 97110** bundled on same lumbar region (CMS PTP edit) |
| Billing insight | “Apply Modifier 59?” or review conflict |
| Timer | Active segment = 97140 |

---

### Step 7 — Unit logic check (optional, ~8 min billing)

To see **Unit 2** without waiting 8 real minutes, use the backend simulated clock:

| Action | Wait |
|--------|------|
| Send another therapist line with `elapsed_seconds` advanced in API, **or** let billing timer run ~8 min while session is **running** with CPT applied | 8+ min billing on timed CPT |

**Expect**

| Panel | What should happen |
|-------|-------------------|
| Units | `1 Unit` → `2 Units` after 8 billed minutes on timed codes |
| Display | `Unit 2 at 16:00` · countdown resets for next 8-min block |

**Note:** Chat `durationSeconds` affects backend chunk window only — it does **not** jump the session or billing clock anymore.

---

### Step 8 — Stop & Path C

| Action | Wait |
|--------|------|
| Tap **Stop** | Finalize loads documentation |

**Expect:** SOAP + summary (Path C) from full transcript.

---

## Cheat sheet — when to wait vs. act

| Moment | Wait? | What to check |
|--------|-------|----------------|
| After every send | **2–5 sec** | Pipeline poll, entities, suggestions |
| After **Apply** | **2 sec** | Billing timer started? NCCI alert? |
| After **Pause** | **5 sec** | Both timers frozen |
| Before duplicate CPT line | — | Only one suggestion for same CPT+region |
| Before applying 2nd CPT | — | Read NCCI warning on card + alert after apply |
| Checking units | **8 min billed** | Not 8 min session clock |
| Transcript timestamps | — | Message time = **when sent**, not word-count duration |

---

## Expected alert & conflict timeline (summary)

```
Step 1  Patient symptoms     → Path B clinical_context (maybe)
Step 2  Therapeutic exercise → Suggest 97110 → Apply → Billing timer ON
Step 3  Repeat ther ex       → NO duplicate suggestion
Step 5  Neuro re-ed          → Suggest 97112 → NCCI warn vs 97110 → Apply → Alert
Step 6  Manual therapy       → Suggest 97140 → NCCI warn vs 97110 → Apply → Alert
```

---

## Minimal 4-line version (quick smoke test)

If you only have 2 minutes:

1. **Patient:** `My lower back hurts 6/10 for two weeks.` → wait → Path B only  
2. **Therapist:** `Starting therapeutic exercise for lumbar stretching.` → wait → Apply **97110** → billing timer runs  
3. **Therapist:** `Continuing therapeutic exercise with resistance band.` → wait → **no** duplicate suggestion  
4. **Therapist:** `Manual therapy soft tissue mobilization on lumbar spine.` → Apply **97140** → **NCCI alert** vs 97110  

---

## Troubleshooting

| Problem | Likely cause |
|---------|----------------|
| Billing timer stuck at 0 | No suggestion **Applied**, or session **Paused** |
| Session timer jumps on send | Fixed — should track wall clock; if not, hard-refresh |
| Two 97110 suggestions | Bug — dismiss one; second should not appear while first is `suggested` |
| Path B never fires | `PATH_B_ENABLED` off, or interval cooldown — wait 20–30 sec between chunks |
| No NCCI warning | Region not US, or CPTs on different body regions (modifier 59 path) |

---

*Aligned with Medexa pipeline overhaul: decoupled clocks, suggestion dedup, Path B `clinical_context`, NCCI on generate + apply.*
