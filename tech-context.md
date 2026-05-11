# Main Mission — Technical Context

> Living reference for the actual implementation. Keep this updated when making significant changes. Companion to `techspec.md` (which covers product intent); this covers what is actually built and how it works.

---

## Stack

| Layer | Tech |
|-------|------|
| Runtime | Python 3.11, FastAPI, Uvicorn |
| Hosting | Railway (auto-deploy from `main` branch) |
| Database | Firebase Firestore (primary) |
| LLM | OpenAI gpt-4o-mini (responses) / gpt-4o (plan gen, watchers, memory) |
| WhatsApp BSP | Wati (live-mt-server.wati.io) |
| Payments | Razorpay (subscriptions API) |
| Scheduler | APScheduler (AsyncIOScheduler, IST timezone) |
| Auth | HMAC-signed cookie, 30-day expiry (`SESSION_SECRET` env var) |

---

## Repository Structure

```
main-mission-agent/
├── main.py                        # FastAPI app, webhook endpoint, dedup, lifespan
├── config/
│   └── settings.py                # All env vars with defaults
├── agents/
│   ├── master_agent.py            # Webhook routing: runner / coach / unknown
│   ├── coach_agent.py             # Runner response pipeline (LLM + gating)
│   ├── onboarding_agent.py        # WhatsApp onboarding conversation (Firestore-backed)
│   ├── template_selector.py       # Plan intent handlers (query/reschedule/tweak)
│   ├── prompt_store.py            # Firebase-backed dynamic prompts with in-process cache
│   ├── prompts.py                 # build_runner_prompt() (legacy, used by test UI)
│   ├── coaching_kb.py             # Selective KB section injection by intent + keywords
│   ├── memory_builder.py          # Nightly incremental runner memory summarization
│   ├── system_watcher.py          # Nightly AI audit of all conversations → observations
│   ├── coach_watcher.py           # Nightly per-coach coaching quality observations
│   └── running_coach_knowledge_base.md  # 35KB, 20 parts — seeded to Firebase
├── integrations/
│   ├── firebase_db.py             # All Firestore reads/writes (FirebaseClient class)
│   ├── llm.py                     # AsyncOpenAI wrapper (LLMClient.complete())
│   ├── whatsapp.py                # Wati API: send_text, send_template, send_runner_message
│   ├── razorpay.py                # Subscription creation + webhook handlers
│   ├── race_lookup.py             # Firebase fuzzy match → DuckDuckGo → LLM extraction
│   └── strava.py                  # Strava activity URL regex + public context fetch
├── routers/
│   ├── auth.py                    # DashboardAuthMiddleware + /login /logout routes
│   ├── dashboard.py               # Coach dashboard (HTML + all /dashboard/api/* endpoints)
│   ├── sysobservations.py         # /sysobservations — system watcher dashboard
│   ├── coachobservations.py       # /coachobservations — coach watcher dashboard
│   └── test_ui.py                 # /test — simulate runner messages without WhatsApp
├── scheduler/
│   └── jobs.py                    # Cron jobs: morning, evening, digest, watchers, memory
├── templates/
│   └── catalog.py                 # All Wati template definitions + fill_template()
├── utils/
│   ├── intent_classifier.py       # Keyword-based intent routing
│   ├── escalation.py              # should_escalate() + notify_coach()
│   └── helpers.py                 # normalize_phone(), weeks_until()
├── scripts/
│   ├── seed_coaching_kb.py        # Seed KB markdown to Firebase system_prompts
│   ├── seed_races.py              # Seed 29 major Indian races to Firebase
│   ├── manual_onboard.py          # CLI: start onboarding for an existing runner
│   └── generate_samples.py        # Preview filled templates before Wati submission
└── tests/                         # pytest suite
```

---

## Firestore Collections

### `runners`
One document per runner. Document ID = `runner_id` (B-prefix 10-char alphanumeric, e.g. `B3F9K2X1M7`).

| Field | Type | Notes |
|-------|------|-------|
| `runner_id` | str | Primary key |
| `name` | str | Full name |
| `phone` | str | Raw phone from Wati |
| `phone_normalized` | str | Canonical form with `+91` prefix — used for all lookups |
| `coach_id` | str | FK → coaches |
| `race_goal` | str | Primary upcoming race name |
| `race_date` | str | ISO date |
| `race_distance` | str | e.g. "42.2km" |
| `races` | list | All races: `[{name, date, distance}]` |
| `weekly_days` | int/str | Training days per week |
| `fitness_level` | str | Beginner / Intermediate / Advanced |
| `injuries` | str | Free text from onboarding |
| `additional_notes` | str | Open-ended "anything else" from onboarding |
| `status` | str | Active / Pending / Inactive |
| `payment_status` | str | Paid / Unpaid |
| `payment_link` | str | Razorpay subscription short_url |
| `monthly_fee` | float | In INR |
| `onboarded` | str | "TRUE" / "FALSE" |
| `start_date` | str | ISO date |
| `notes` | str | Misc (e.g. subscription_id) |
| `created_at` | str | IST timestamp |

### `training_plans`
One document per runner per day. Document ID = `PLAN_{uuid[:8]}`.

| Field | Type | Notes |
|-------|------|-------|
| `plan_id` | str | Primary key |
| `runner_id` | str | FK → runners |
| `date` | str | ISO date |
| `day_type` | str | Run / Rest / Cross-train |
| `session_type` | str | Easy Run / Tempo Run / Interval Training / Fartlek / Long Run / Recovery Run / Rest |
| `distance_km` | str | Total distance (0 for time/rep-based) |
| `duration_min` | str | For time-based sessions |
| `reps` | str | For intervals, e.g. "8" |
| `rep_distance_m` | str | e.g. "400" for 400m intervals |
| `intensity` | str | Zone 2 / Threshold / VO2 Max / Easy / Rest |
| `rpe_target` | str | e.g. "4-5" |
| `coach_notes` | str | Coaching cue for this session |
| `workout_notes` | str | General workout type tips |
| `sent` | str | "TRUE" / "FALSE" — whether morning message was sent |
| `sent_at` | str | IST timestamp |
| `completed` | str | "TRUE" / "FALSE" |
| `actual_distance` | str | Runner-reported actual distance |
| `rpe_actual` | str | Runner-reported RPE |
| `runner_feedback` | str | Raw feedback message from runner |
| `flags` | str | e.g. "injury" |

### `plan_requests`
Runner-initiated plan change requests. Document ID = `REQ_{uuid[:6]}`.

| Field | Type | Notes |
|-------|------|-------|
| `request_id` | str | Primary key |
| `runner_id` | str | FK → runners |
| `coach_id` | str | FK → coaches |
| `request_type` | str | "reschedule" / "tweak" / "skip" |
| `description` | str | LLM-cleaned one-sentence description |
| `session_date` | str | ISO date of the session being requested to change |
| `plan_id` | str | FK → training_plans (if found) |
| `status` | str | pending / resolved / dismissed |
| `created_at` | str | IST timestamp |
| `resolved_at` | str | IST timestamp |
| `resolution` | str | Resolution note |

### `coaches`
One document per coach. Document ID = `coach_id`.

| Field | Type | Notes |
|-------|------|-------|
| `coach_id` | str | Primary key |
| `coach_name` | str | |
| `coach_phone` | str | |
| `coach_phone_normalized` | str | |
| `status` | str | Active / Inactive |
| `active_prompt_version` | str | e.g. "v3" |
| `system_prompt_v1` / `v2` … | str | Versioned system prompts |

### `rules`
Coach corrections and instructions. Document ID = `RULE_{uuid[:6]}`.

| Field | Type | Notes |
|-------|------|-------|
| `rule_id` | str | |
| `coach_id` | str | |
| `rule_derived` | str | The actual rule text injected into LLM system prompt |
| `status` | str | Active / Archived |
| `source` | str | coach_correction / coach_instruction / coach_dashboard |
| `situation` | str | Original raw message that triggered the rule |
| `date_added` | str | |

### `conversations`
All inbound and outbound messages. Document ID = `LOG_{uuid[:6]}` (inbound) + `LOG_{uuid[:6]}_r` (outbound).

| Field | Type | Notes |
|-------|------|-------|
| `log_id` | str | |
| `timestamp` | str | IST timestamp |
| `runner_id` | str | |
| `coach_id` | str | |
| `direction` | str | inbound / outbound |
| `message` | str | Message text |
| `message_type` | str | Intent/type: feedback, plan_query, coach_direct, coach_handback, coach_takeover, session_reminder, payment_reminder, conversation_close, greeting, … |
| `handled_by` | str | agent / coach |
| `escalated` | bool | |
| `escalation_reason` | str | |

### `system_prompts`
Dynamic editable prompts. Document ID = prompt key (e.g. `onboarding`, `creative_vars_system`, `coach_response_system`, `coaching_knowledge`).

| Field | Type | Notes |
|-------|------|-------|
| `prompt_id` | str | |
| `content` | str | Current prompt text |
| `version` | int | Auto-incremented |
| `updated_at` | str | |
| `last_changed_by` | str | |
| `versions` | list | Last 20 versions for undo |

### `onboarding_sessions`
Active onboarding conversations. Document ID = phone number (normalized). Deleted on completion.

| Field | Type | Notes |
|-------|------|-------|
| `phone` | str | |
| `history` | list | `[{role, content}]` OpenAI message format |
| `coach_id` | str | |
| `name` | str | |
| `runner_id` | str | |
| `prefilled` | dict | Data already known, skipped in questions |
| `system` | str | Full system prompt for this session |
| `updated_at` | str | |

### `runner_memory`
Nightly AI-generated summaries per runner. Document ID = `runner_id`.

| Field | Type | Notes |
|-------|------|-------|
| `runner_id` | str | |
| `summary` | str | Overall background and training history |
| `known_issues` | str | Recurring injuries, concerns |
| `coaching_notes` | str | Coaching style observations |
| `recent_form` | str | Last 1-2 weeks of training quality |
| `watch_points` | str | Things to monitor |
| `last_updated` | str | IST timestamp — used for incremental updates |

### `races`
Race calendar. Document ID = slugified race name.

| Field | Type | Notes |
|-------|------|-------|
| `name` | str | Canonical race name |
| `date` | str | ISO date (empty if unconfirmed) |
| `city` | str | |
| `distances` | list | e.g. `["42.2km", "21.1km", "10km"]` |
| `updated_at` | str | |

### `webhook_dedup`
Wati retry deduplication. Document ID = Wati message ID. Written before processing; checked on receipt.

### `platform_events`
Audit log for payments, onboarding, escalations, errors. Document ID = auto.

### `system_observations` / `coach_observations`
Nightly watcher output — AI-generated issues and suggested prompt fixes, with apply/undo support.

---

## Message Flow (Inbound)

```
Wati webhook POST /webhook
  → dedup check (in-memory set + Firestore webhook_dedup)
  → asyncio.create_task(handle_incoming(data))   # return 200 immediately
      → master_agent.handle_incoming()
          → identify_sender(phone)
              runner (onboarded=FALSE)  → onboarding_agent
              runner (payment_status=Unpaid) → payment reminder
              runner (active)           → coach_agent.handle_runner_message()
              coach                     → coach_agent.handle_coach_message()
              unknown                   → create provisional runner → onboarding_agent
```

### Runner Response Pipeline (`coach_agent.generate_runner_response`)

```
1. Load: runner_data, all_plans, todays_plan, memory, recent_messages (last 10)
2. Coach takeover check — if coach messaged in last 30 min, stay silent
3. Conversation gating:
   - Closer ("Ok", "thanks", "👍" …) → no reply
   - Greeting ("Hi", "Hey" …) → "Hey! What's on your mind?"
4. classify_intent(message) — keyword-based
5. Route:
   - race_update    → _handle_race_update() [LLM extracts race + lookup_race()]
   - plan_query     → _handle_plan_query() [fetches real plan, no LLM hallucination]
   - plan_reschedule/tweak → _handle_plan_change_request() [creates plan_request in Firestore]
   - everything else → _generate_llm_response() [free-form LLM reply]
6. log_conversation() + update_plan_feedback()
7. Escalation check → if injury/dropout → notify_coach() via WhatsApp
8. whatsapp.send_text(runner_phone, response)
```

### LLM Response Generation (`_generate_llm_response`)

System prompt layers (in order, each overrides previous):
1. `coach_response_system` from Firebase/prompt_store — tone rules
2. Coaching KB sections (selective injection via `coaching_kb.get_coaching_context`)
3. Coach rules from `rules` collection — highest priority
4. Hardcoded behavioural guardrails (appended in code, not editable from Firebase):
   - Don't repeat concerns from previous message
   - Medical/supplement questions → redirect to coach/doctor
   - Use KB over generic advice
   - 2-3 sentence max

User message contains:
- Runner profile (name, race, fitness level, weekly days, injuries)
- Today's plan (full detail: type, distance/reps, intensity, RPE, coach notes, workout notes)
  - If rest day: next upcoming session from next 14 days (prevents hallucination)
- Runner memory (summary, known_issues, recent_form, watch_points)
- Last 8 conversation messages
- Runner's current message

---

## Intent Classification

Used for routing only — not for template selection (templates removed from conversational path).

| Intent | Trigger | Action |
|--------|---------|--------|
| `injury_flag` | pain/hurt/sore/ache/strain/etc. | LLM responds + escalate to coach |
| `dropout_risk` | quit/give up/drop out/etc. | LLM responds + escalate to coach |
| `plan_reschedule` | reschedule/move the/postpone/etc. + compound "move" + day name | Create plan_request |
| `plan_tweak` | make it shorter/easier/can i skip/adjust/etc. | Create plan_request |
| `plan_query` | what's my plan/next run/give me details/what distance/etc. | Fetch real plan data |
| `race_update` | signed up for/registered for/also running/etc. | Race lookup + add to runner |
| `missed_session` | missed/skipped/couldn't/didn't run/etc. | LLM responds |
| `feedback` | done/completed/finished/ran/km/etc. | LLM responds |
| `conversation_close` | ok/okay/thanks/👍/got it/etc. | No reply |
| `greeting` | hi/hello/hey/good morning/etc. | "Hey! What's on your mind?" |
| `question` | default | LLM responds |

---

## Plan Intent Handlers (`template_selector.py`)

These bypass the LLM entirely for plan data — the LLM was hallucinating plan details.

**`_handle_plan_query(runner, today_plan, message)`**
- "next run/session/workout" → scans next 21 days, finds first non-rest session
- Detail follow-ups ("give me details", "what distance", "how far", "as per plan") → checks today → tomorrow → next upcoming
- Specific day ("tomorrow", "Monday", "this week") → `get_plan_by_date()` or `get_runner_plans()` for week view
- Returns formatted `plan_today_detail` or `plan_week_view` template string directly

**`_handle_plan_change_request(runner, today_plan, message, request_type)`**
- Calls LLM with 80-token max to extract a clean one-sentence description of the request
- Creates a `plan_request` document in Firestore
- Returns `plan_reschedule_flagged` or `plan_tweak_flagged` template confirming to runner

---

## WhatsApp Send Strategy

Two send paths:

| Function | When to use | Behaviour |
|----------|------------|-----------|
| `whatsapp.send_text(phone, msg)` | Reply to inbound (window always open) | Direct session message via Wati |
| `send_runner_message(runner, msg)` | Proactive / coach-initiated sends | Checks 24h window: send_text if open, `mm_question_general` template if closed |

The 24h window is checked via `is_within_session_window(runner_id)` — looks at last inbound message timestamp in `conversations`.

---

## Proactive Scheduled Jobs

All jobs run IST timezone (APScheduler).

| Job | Time | What it does |
|-----|------|-------------|
| `send_morning_messages` | 6:00 AM | Sends today's session (or rest day) to all active runners with a plan |
| `evening_checkin` | 7:00 PM | Sends check-in to runners with no feedback on today's sent session |
| `send_coach_digest` | 9:00 PM | Sends daily summary to each coach (X/Y completed, N flagged) |
| `_run_coach_watcher` | 10:00 PM | AI reviews each coach's conversations → observations + suggestions |
| `_run_system_watcher` | 11:30 PM | AI reviews all conversations → pattern issues + prompt fixes |
| `_build_runner_memories` | 1:00 AM | Incremental summarization of each runner's conversation history |

---

## Prompt Store

All prompts live in Firestore `system_prompts` and are cached in-process. Edit from `/sysobservations` dashboard or directly in Firebase. Defaults in `prompt_store._DEFAULTS` are seeded on first access.

| Prompt ID | Used by | Purpose |
|-----------|---------|---------|
| `onboarding` | `onboarding_agent` | 6-question onboarding conversation prompt |
| `creative_vars_system` | `template_selector._fill_creative_vars` | Tone rules for filling template variables (JSON output) |
| `coach_response_system` | `coach_agent._generate_llm_response` | Tone rules for free-form conversational replies (plain text) |
| `creative_vars_user` | `template_selector._fill_creative_vars` | User message template for creative var filling |
| `coaching_knowledge` | `coaching_kb.get_coaching_context` | 35KB running coach KB, selectively injected |

### Coaching KB Injection Logic (`coaching_kb.py`)

Always injects: `PART XX` (core principles, ~300 tokens)

Additional sections by intent/keywords:
- `injury_flag` or injury keywords → `PART XI` (injury table + decision tree)
- Nutrition keywords (eat/food/carb/gel/etc.) → `PART X`
- `question` + workout keywords (tempo/interval/zone/etc.) → `PART V` + `PART II`
- `feedback` or `missed_session` → `PART IX` (recovery)

---

## Onboarding Flow

1. Unknown number messages → `master_agent` creates provisional runner (status=Pending, payment_status=Unpaid)
2. `start_onboarding()` saves session to `onboarding_sessions/{phone}` (Firestore, survives restarts)
3. Each message → `handle_onboarding()` loads session, appends to history, calls LLM, saves back
4. LLM is instructed to collect 6 things: race + distance, training days, injuries, time preference, current mileage, open-ended notes
5. LLM appends `[COMPLETE]` when done → `_complete_onboarding()` runs:
   - Saves structured data to runner document
   - Calls `lookup_race()` for each extracted race
   - Creates Razorpay subscription → saves `payment_link` to runner
   - Sends payment link via WhatsApp
   - Deletes `onboarding_sessions/{phone}`
6. Paid runner (subscription.activated webhook) → marked Active → `send_runner_message` confirmation

---

## Coach Dashboard (`/dashboard`)

Single-page app. All data via `/dashboard/api/*` endpoints.

**Main view:**
- Summary tiles: All / Completed / Pending / Flagged / Rest
- Plan Requests bar (auto-loads): pending runner change requests with Done/Dismiss buttons
- Escalation alert bar: runners with injury/dropout flags
- Runner table with search + race filter

**Side panel (opens on row click):**
- **Today tab**: today's plan with edit form, session reminder button, mark complete
- **History tab**: live chat (6s polling), compose box, optimistic bubbles, coach send
- **Plan tab**: AI plan chat (create/edit plans via natural language), plan list, bulk generate
- **Profile tab**: edit runner details, coach notes, handback to AI button

**Manage AI modal** (header button):
- Prompt editor with version history + restore
- Coach rules: add/archive/delete

**Key endpoints:**
- `GET /dashboard/api/data` — all runners + today's plans in one call
- `GET /dashboard/api/runner/{id}` — full runner detail + plan + history
- `POST /dashboard/api/runner/{id}/plans/generate` — LLM plan generation (gpt-4o)
- `POST /dashboard/api/runner/{id}/plan/chat` — AI plan assistant (gpt-4o)
- `GET /dashboard/api/plan-requests` — pending plan change requests
- `POST /dashboard/api/plan-request/{id}/resolve` / `/dismiss`

---

## Coach Takeover / Handback

When a coach sends a manual WhatsApp message from the dashboard:
- Logged with `message_type: "coach_direct"`
- AI checks recent messages in `_coach_recently_messaged()` — if `coach_direct` within 30 min (and no `coach_handback` since), AI stays silent
- Coach clicks "Handback to AI" in dashboard → logs `message_type: "coach_handback"` → AI resumes

---

## Runner Memory

Built nightly by `memory_builder.py` at 1 AM IST:
- First build: summarizes all conversations
- Subsequent: loads existing memory + only new messages since `last_updated` → LLM generates incremental update
- Stored in `runner_memory/{runner_id}`
- Injected into `_generate_llm_response` as long-term context block
- Model: `OBSERVATIONS_MODEL` (gpt-4o by default)

---

## Razorpay Integration

**Subscription flow:**
1. `create_subscription()` → POST `/v1/subscriptions` with `notes: {name, whatsapp_number, coach_id, runner_id}`
2. Runner pays via `short_url`
3. `subscription.activated` webhook → find runner by `runner_id` from notes → mark Active → send confirmation
4. Recurring `invoice.paid` / `subscription.charged` → log renewal

**Signature verification:** HMAC-SHA256 of raw body with `RAZORPAY_WEBHOOK_SECRET`

Note: `callback_url` cannot be set via API — configure redirect in Razorpay dashboard → Settings → Plan.

---

## Auth

All dashboard routes (`/dashboard`, `/sysobservations`, `/coachobservations`, `/test`) protected by `DashboardAuthMiddleware`.

- Set `DASHBOARD_CODE` env var (any string) to enable protection
- Leave empty to disable (useful in development)
- Cookie: `mm_auth` — HMAC-SHA256 signed, 30-day expiry, httponly, samesite=lax
- `SESSION_SECRET` env var is the signing key

---

## Environment Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `OPENAI_API_KEY` | — | Required |
| `OPENAI_MODEL` | `gpt-4o-mini` | Default model for runner responses |
| `OBSERVATIONS_MODEL` | `gpt-4o` | Watchers, memory builder, plan generation |
| `WATI_API_URL` | — | e.g. `https://live-mt-server.wati.io/xxxxx` |
| `WATI_API_TOKEN` | — | Bearer token |
| `FIREBASE_CREDENTIALS_JSON` | — | Full service account JSON as string |
| `FIREBASE_PROJECT_ID` | — | |
| `RAZORPAY_KEY_ID` | — | |
| `RAZORPAY_KEY_SECRET` | — | |
| `RAZORPAY_WEBHOOK_SECRET` | — | For signature verification |
| `RAZORPAY_PLAN_ID` | — | Create once in Razorpay dashboard, reuse forever |
| `WEBHOOK_SECRET_TOKEN` | — | Appended as `?token=` by Wati |
| `DASHBOARD_CODE` | — | Entry code for all dashboard routes |
| `SESSION_SECRET` | `mm-default-secret-change-me` | HMAC signing key for auth cookie |
| `APP_URL` | `https://web-production-a1ef8.up.railway.app` | Used in payment links |
| `DEFAULT_COACH_ID` | `COACH_A` | Assigned to unknown-number signups |
| `WHATSAPP_BUSINESS_PHONE` | `919019585359` | For wa.me links on payment success page |
| `SUPPORT_EMAIL` | `indiranagarrunclub@gmail.com` | Shown to unpaid runners needing help |
| `MORNING_MESSAGE_HOUR` | `6` | IST hour |
| `EVENING_CHECKIN_HOUR` | `19` | IST hour |
| `DIGEST_HOUR` | `21` | IST hour |
| `SYSTEM_WATCHER_HOUR` | `23` | IST hour |
| `COACH_WATCHER_HOUR` | `22` | IST hour |
| `MEMORY_BUILD_HOUR` | `1` | IST hour |

---

## Templates (Wati-Approved)

Templates are only used for **proactive outbound** messages when the 24h session window is closed. Conversational replies always use `send_text`.

Proactive templates in use:
- `mm_morning_run` — daily session nudge
- `mm_morning_rest_day` — rest day message
- `mm_evening_checkin` — evening check-in for no-feedback runners
- `mm_question_general` — generic fallback for `send_runner_message` when window expired
- `mm_weekly_summary` — Sunday evening summary

Plan/coaching response templates (session window always open for these):
- `plan_today_detail`, `plan_week_view`, `plan_no_session`
- `plan_tweak_flagged`, `plan_reschedule_flagged`
- `injury_response`, `missed_first_time`, `missed_multiple`, `dropout_risk`
- `feedback_solid`, `feedback_great`, `feedback_tough`

---

## Webhook Deduplication

Two-layer to handle Wati's aggressive retry behaviour:

1. **In-memory set** (`_processed_ids`) — fast path, cleared on restart, capped at 500 entries
2. **Firestore `webhook_dedup/{message_id}`** — durable across restarts

Both checked before `asyncio.create_task(handle_incoming(data))`. Response is returned immediately (before processing) so Wati doesn't retry.

---

## Race Lookup (`race_lookup.py`)

1. Fuzzy match against `races` Firestore collection (case-insensitive substring)
2. If found but `date` is empty → web search to fill date
3. If not found → DuckDuckGo web search → LLM extracts name/date/distances → upsert to `races`

Used during onboarding and `race_update` intent handling.

---

## Known Constraints / Gotchas

- **Wati send_text**: message goes as query param `?messageText=…`, not JSON body
- **Razorpay notes**: sent as `[]` (empty list) when no notes set — always check `isinstance(notes, list)`
- **WhatsApp 24h window**: all inbound-triggered replies are within window. Use `send_runner_message()` for anything proactive
- **Coach takeover stops at coach_handback**: `_coach_recently_messaged()` walks back through messages and stops at either `coach_handback` (resumes AI) or `coach_direct` within 30 min (silences AI)
- **`coach_response_system` vs `creative_vars_system`**: former is for free-form replies (plain text), latter is for template variable filling (JSON). They must not be mixed — `creative_vars_system` appends "Return only valid JSON" in code, not in Firebase
- **Firestore composite indexes**: avoided by filtering in Python after single-field queries
- **Railway restart**: onboarding sessions and webhook dedup both use Firestore, so restarts don't lose state
