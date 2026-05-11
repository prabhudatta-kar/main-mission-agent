# Main Mission — WhatsApp Coaching Agent System
## Technical Specification

**Version:** 2.0
**Date:** May 2026
**Status:** Live on Railway — this document reflects the current production implementation

> For full implementation detail (Firestore schemas, message flows, file-by-file breakdown), see `tech-context.md`.

---

## 1. What We Are Building

A WhatsApp-based AI coaching system for Main Mission, a running coaching platform in Bangalore, India.

Runners receive personalised daily training instructions via WhatsApp. Coaches manage their runners via a web dashboard and WhatsApp. An AI agent sits in the middle — routing messages, generating responses, logging data, learning from coach corrections, and alerting coaches to problems.

**Interfaces:**
- **Runner** — WhatsApp only (no app)
- **Coach** — Web dashboard (`/dashboard`) + WhatsApp for escalations and digest
- **Platform** — Railway-hosted Python server

---

## 2. System Architecture

```
Wati webhook (inbound WhatsApp)
          │
          ▼
    main.py /webhook
    - Token auth
    - Dedup (memory + Firestore)
    - Fire-and-forget asyncio task
          │
          ▼
  master_agent.handle_incoming()
    - identify_sender (runner / coach / unknown)
    - unknown → create provisional runner → onboarding
    - runner (not onboarded) → onboarding_agent
    - runner (unpaid) → payment reminder
    - runner (active) → coach_agent
    - coach → coach_agent (coach flow)
          │
          ▼
  coach_agent.generate_runner_response()
    - Conversation gating (closers, greetings)
    - Plan intents → template_selector (real data, no LLM)
    - Race update → race_lookup
    - All else → _generate_llm_response() [free-form, plain text]
          │
          ▼
  whatsapp.send_text() or send_template()
  (send_text for inbound replies, send_template for proactive if window closed)
```

---

## 3. Tech Stack

| Component | Tool | Notes |
|-----------|------|-------|
| Language | Python 3.11 | |
| Web framework | FastAPI + Uvicorn | |
| Hosting | Railway.app | Auto-deploy from `main` branch |
| Database | Firebase Firestore | Primary data store — all runners, plans, conversations |
| LLM — responses | OpenAI gpt-4o-mini | Runner-facing conversational replies |
| LLM — analysis | OpenAI gpt-4o | Plan generation, watchers, memory builder |
| WhatsApp BSP | Wati (live-mt-server.wati.io) | Session messages as query param `?messageText=` |
| Payments | Razorpay Subscriptions API | Subscription creation + webhook activation |
| Scheduler | APScheduler (AsyncIOScheduler) | In-process, IST timezone |
| Auth | HMAC-signed cookie | 30-day expiry, protects all dashboard routes |

---

## 4. Data Storage — Firebase Firestore

All data lives in Firestore. Google Sheets is no longer the primary data layer.

### Collections

| Collection | What it stores | Doc ID format |
|------------|---------------|---------------|
| `runners` | Runner profiles | `B` + 9 alphanumeric chars (e.g. `B3F9K2X1M7`) |
| `training_plans` | Per-runner per-day sessions | `PLAN_{uuid[:8]}` |
| `plan_requests` | Runner-requested plan changes | `REQ_{uuid[:6]}` |
| `coaches` | Coach configs + versioned system prompts | `coach_id` |
| `rules` | Coach corrections and instructions | `RULE_{uuid[:6]}` |
| `conversations` | All inbound/outbound messages | `LOG_{uuid[:6]}` |
| `system_prompts` | Dynamic editable LLM prompts | prompt key (e.g. `coach_response_system`) |
| `onboarding_sessions` | Active onboarding conversations | phone number |
| `runner_memory` | Nightly AI summaries per runner | `runner_id` |
| `races` | Indian race calendar | slugified race name |
| `webhook_dedup` | Wati retry deduplication | Wati message ID |
| `platform_events` | Payment/onboarding/error audit log | auto |
| `system_observations` | Nightly system watcher output | auto |
| `coach_observations` | Nightly coach watcher output | auto |

> Full field schemas for each collection are in `tech-context.md`.

---

## 5. Message Flow

### 5.1 Inbound (Runner → AI → Runner)

```
1. Wati POST /webhook
2. Dedup check (in-memory + Firestore)
3. asyncio.create_task → return 200 immediately (prevents Wati retry)
4. identify_sender(phone) → runner / coach / unknown
5. Runner pipeline:
   a. Load runner data, today's plan, memory, last 10 messages
   b. Coach takeover check (30-min window after coach_direct message)
   c. Conversation gating:
      - Closer (ok/thanks/👍) → no reply
      - Greeting (hi/hey) → "Hey! What's on your mind?"
   d. classify_intent(message) — keyword-based
   e. Route:
      - race_update → race lookup + add to runner
      - plan_query → fetch real plan data, return formatted string
      - plan_reschedule/tweak → create plan_request in Firestore, confirm to runner
      - injury/dropout → LLM reply + escalate to coach via WhatsApp
      - everything else → _generate_llm_response()
   f. log_conversation()
   g. whatsapp.send_text(runner_phone, response)
```

### 5.2 LLM Response Generation

System prompt layers (each overrides previous):
1. `coach_response_system` from Firestore — tone rules (plain text, no JSON)
2. Coaching KB sections — selective injection by intent + keywords
3. Coach rules from `rules` collection
4. Hardcoded guardrails (not editable from Firebase):
   - Don't repeat the same concern from the previous message
   - Medical/supplement questions → redirect to coach/doctor
   - Use coaching KB over generic advice
   - 2-3 sentences maximum

User message includes: runner profile, today's plan (full detail), runner memory, last 8 conversation messages, runner's current message.

---

## 6. Intent Classification

Keyword-based. Used for routing to special handlers and escalation — **not** for template selection (conversational replies are always free-form).

| Intent | Route |
|--------|-------|
| `injury_flag` | LLM reply + escalate to coach |
| `dropout_risk` | LLM reply + escalate to coach |
| `plan_query` | Fetch real plan from Firestore, return formatted string |
| `plan_reschedule` | Create plan_request, confirm to runner |
| `plan_tweak` | Create plan_request, confirm to runner |
| `race_update` | Extract race, lookup, add to runner profile |
| `missed_session` | LLM reply |
| `feedback` | LLM reply |
| `conversation_close` | No reply |
| `greeting` | "Hey! What's on your mind?" |
| `question` | LLM reply |

---

## 7. Scheduled Jobs (All IST)

| Time | Job | What it does |
|------|-----|-------------|
| 6:00 AM | Morning messages | Sends today's session to all active runners with a plan |
| 7:00 PM | Evening check-in | Nudges runners who have a sent plan but no feedback |
| 9:00 PM | Coach digest | X/Y completed, N flagged — sent to each coach via WhatsApp |
| 10:00 PM | Coach watcher | AI reviews each coach's conversations → observations |
| 11:30 PM | System watcher | AI reviews all conversations → pattern issues + prompt fixes |
| 1:00 AM | Memory builder | Incremental runner memory summarization |

---

## 8. WhatsApp Send Rules

The 24-hour session window determines which send method to use:

| Scenario | Method |
|----------|--------|
| Reply to inbound message | `whatsapp.send_text()` — window always open |
| Proactive / coach dashboard send | `send_runner_message()` — checks window, falls back to `mm_question_general` template |

---

## 9. Prompt Architecture

All prompts stored in Firestore `system_prompts`, cached in-process, editable from `/sysobservations` dashboard.

| Prompt ID | Purpose |
|-----------|---------|
| `onboarding` | 6-question onboarding conversation |
| `coach_response_system` | Tone rules for conversational replies (plain text output) |
| `creative_vars_system` | Tone rules for template variable filling (JSON output) |
| `creative_vars_user` | User message template for creative var filling |
| `coaching_knowledge` | 35KB running coach KB (20 parts), selectively injected |

### Coaching KB Injection

Always includes: PART XX (core principles)

Additional by intent/keywords:
- Injury → PART XI (injury table + decision tree)
- Nutrition keywords → PART X
- Workout questions → PART V + PART II
- Feedback / missed session → PART IX (recovery)

---

## 10. Onboarding Flow

1. Unknown number messages → provisional runner created (Pending, Unpaid)
2. `start_onboarding()` → saves session to `onboarding_sessions/{phone}` (Firestore)
3. LLM conversation collects: race + distance, training days, injuries, time preference, current mileage, open-ended notes
4. On `[COMPLETE]`:
   - Saves structured data to runner document
   - Looks up each race via `race_lookup()`
   - Creates Razorpay subscription → sends payment link via WhatsApp
   - Deletes onboarding session
5. `subscription.activated` webhook → mark runner Active → send confirmation

---

## 11. Coach Dashboard (`/dashboard`)

Single-page app with all data via `/dashboard/api/*` endpoints.

**Main view:** Summary tiles + Plan Requests bar + Escalation bar + runner table

**Side panel per runner:**
- Today: plan details, edit form, send reminder, mark complete
- History: live chat (6s poll), coach compose, coach send
- Plan: AI plan assistant (gpt-4o), plan list, bulk generate
- Profile: edit runner, coach notes, handback to AI

**Manage AI modal:** Prompt editor with version history, coach rules management

---

## 12. Auth

All dashboard routes protected by `DashboardAuthMiddleware`.

- `DASHBOARD_CODE` — entry code (set in Railway env vars)
- `SESSION_SECRET` — HMAC signing key for auth cookie (set a long random string, do not leave as default in production)
- Cookie: `mm_auth`, 30-day expiry, httponly, samesite=lax
- Leave `DASHBOARD_CODE` empty to disable protection (local development)

---

## 13. Payments (Razorpay)

- Subscription plan created once in Razorpay dashboard → `RAZORPAY_PLAN_ID` env var
- `create_subscription()` → POST `/v1/subscriptions` with runner details in `notes`
- `subscription.activated` webhook → runner marked Active + confirmation WhatsApp sent
- Recurring renewals → logged to `platform_events`
- `callback_url` cannot be set via API — configure redirect in Razorpay dashboard → Settings → Plan → set to `{APP_URL}/payment-success`

---

## 14. Environment Variables

```bash
# OpenAI
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
OBSERVATIONS_MODEL=gpt-4o

# Wati (WhatsApp)
WATI_API_URL=https://live-mt-server.wati.io/xxxxx
WATI_API_TOKEN=
WATI_API_KEY=                        # separate key for template management
WEBHOOK_SECRET_TOKEN=                 # appended as ?token= by Wati

# Firebase
FIREBASE_CREDENTIALS_JSON=           # full service account JSON as string
FIREBASE_PROJECT_ID=

# Razorpay
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
RAZORPAY_PLAN_ID=                    # create once in dashboard, reuse forever

# Dashboard auth
DASHBOARD_CODE=                      # entry code for all dashboard routes
SESSION_SECRET=                      # HMAC signing key — set a long random string

# App
APP_URL=https://web-production-a1ef8.up.railway.app
APP_ENV=production
TIMEZONE=Asia/Kolkata
DEFAULT_COACH_ID=COACH_A
WHATSAPP_BUSINESS_PHONE=919019585359
SUPPORT_EMAIL=indiranagarrunclub@gmail.com
PAYMENT_LINK=                        # optional fallback payment link

# Scheduler (IST hours)
MORNING_MESSAGE_HOUR=6
EVENING_CHECKIN_HOUR=19
DIGEST_HOUR=21
SYSTEM_WATCHER_HOUR=23
COACH_WATCHER_HOUR=22
MEMORY_BUILD_HOUR=1
```

---

## 15. File Structure

```
main-mission-agent/
├── main.py                      # FastAPI app, /webhook, /razorpay/webhook, /payment-success
├── config/settings.py           # All env vars with defaults
│
├── agents/
│   ├── master_agent.py          # Webhook routing: runner / coach / unknown
│   ├── coach_agent.py           # Runner response pipeline + gating + LLM
│   ├── onboarding_agent.py      # WhatsApp onboarding (Firestore-backed sessions)
│   ├── template_selector.py     # Plan query/reschedule/tweak handlers (real data)
│   ├── prompt_store.py          # Firebase prompt cache + hardcoded defaults
│   ├── prompts.py               # build_runner_prompt() (used by test UI)
│   ├── coaching_kb.py           # Selective KB section injection
│   ├── memory_builder.py        # Nightly incremental runner memory
│   ├── system_watcher.py        # Nightly system-wide conversation audit
│   ├── coach_watcher.py         # Nightly per-coach quality observations
│   └── running_coach_knowledge_base.md   # 35KB KB source (seeded to Firebase)
│
├── integrations/
│   ├── firebase_db.py           # All Firestore reads/writes (FirebaseClient)
│   ├── llm.py                   # AsyncOpenAI wrapper
│   ├── whatsapp.py              # Wati: send_text, send_template, send_runner_message
│   ├── razorpay.py              # Subscription creation + webhook handlers
│   ├── race_lookup.py           # Firebase → web search → LLM extraction
│   └── strava.py                # Strava URL context fetch
│
├── routers/
│   ├── auth.py                  # DashboardAuthMiddleware + /login /logout
│   ├── dashboard.py             # Coach dashboard (HTML + /dashboard/api/*)
│   ├── sysobservations.py       # System watcher dashboard
│   ├── coachobservations.py     # Coach watcher dashboard
│   └── test_ui.py               # /test — simulate messages without WhatsApp
│
├── scheduler/jobs.py            # All cron jobs
├── templates/catalog.py         # Wati template definitions + fill_template()
│
├── utils/
│   ├── intent_classifier.py     # Keyword-based intent routing
│   ├── escalation.py            # should_escalate() + notify_coach()
│   └── helpers.py               # normalize_phone(), weeks_until()
│
├── scripts/
│   ├── seed_coaching_kb.py      # Seed KB markdown → Firebase
│   ├── seed_races.py            # Seed 29 Indian races → Firebase
│   ├── manual_onboard.py        # CLI: start onboarding for existing runner
│   └── generate_samples.py      # Preview filled templates
│
└── tests/                       # pytest suite
```

---

## 16. Key Constraints and Gotchas

- **Wati send_text**: message goes as query param `?messageText=`, not JSON body
- **WhatsApp 24h window**: inbound replies always use `send_text`. Proactive sends use `send_runner_message()` which checks the window and falls back to template
- **Razorpay notes**: sent as `[]` when empty — always check `isinstance(notes, list)`
- **Webhook dedup**: two-layer — in-memory set (fast) + Firestore (survives restarts). Return 200 before processing to prevent Wati retry
- **`coach_response_system` vs `creative_vars_system`**: former outputs plain text (conversational replies), latter outputs JSON (plan template variable filling). Do not mix
- **Firebase composite indexes**: avoided by filtering in Python after single-field Firestore queries
- **Coach takeover**: `_coach_recently_messaged()` walks back through conversations — stops at `coach_handback` (AI resumes) or `coach_direct` within 30 min (AI stays silent)
- **Onboarding sessions persist across Railway restarts**: stored in Firestore, not in-memory

---

## 17. Cost at Scale

| Component | 100 runners | 500 runners | 1,000 runners |
|-----------|------------|------------|--------------|
| Wati/BSP | ₹999 | ₹2,999 | ₹4,999 |
| Meta conversation charges | ₹700 | ₹3,500 | ₹7,000 |
| OpenAI (responses, gpt-4o-mini) | ~₹500 | ~₹2,500 | ~₹5,000 |
| OpenAI (watchers + memory, gpt-4o) | ~₹5,000 | ~₹25,000 | ~₹50,000 |
| Firebase | Free tier | ~₹1,000 | ~₹3,000 |
| Railway hosting | ₹500 | ₹500 | ₹1,000 |
| **Total** | **~₹7,700** | **~₹35,500** | **~₹71,000** |
| Revenue (₹1,500/runner/month) | ₹1,50,000 | ₹7,50,000 | ₹15,00,000 |
| **Infrastructure margin** | **~95%** | **~95%** | **~95%** |

---

*Main Mission Platform — v2.0 — May 2026*
