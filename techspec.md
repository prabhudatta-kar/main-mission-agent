# Main Mission — WhatsApp Coaching Agent System
## Technical Specification for Development

**Version:** 1.0  
**Date:** May 2026  
**Purpose:** Complete technical context for a coding assistant to build the system from scratch  
**Status:** MVP Spec — build this before anything else

---

## 1. What We Are Building

A WhatsApp-based AI coaching system for Main Mission, a running coaching marketplace in Bangalore, India.

Runners receive personalised daily training instructions via WhatsApp. Coaches manage their runners via Google Sheets and WhatsApp. An AI agent sits in the middle — routing messages, generating responses, logging data, and learning from coach corrections.

**No web app. No mobile app. No database. No dashboard to build.**

The entire system runs on:
- WhatsApp (runner and coach interface)
- Google Sheets (data layer + coach view)
- Python server (agent logic)
- LLM API (intelligence layer)

---

## 2. System Architecture

```
                    ┌─────────────────────────────┐
                    │        WHATSAPP API          │
                    │   (Wati / Interakt / Meta)   │
                    └──────────┬──────────────────-┘
                               │ webhook (incoming messages)
                               ▼
                    ┌─────────────────────────────┐
                    │        MASTER AGENT          │
                    │  - Receives all messages     │
                    │  - Identifies sender type    │
                    │  - Routes to correct agent   │
                    │  - Handles onboarding        │
                    │  - Handles platform events   │
                    └──────┬──────────┬────────────┘
                           │          │
               ┌───────────┘          └───────────┐
               ▼                                  ▼
    ┌─────────────────────┐           ┌─────────────────────┐
    │   COACH A AGENT     │           │   COACH B AGENT     │
    │  - Coach A's prompt │           │  - Coach B's prompt │
    │  - Coach A's rules  │           │  - Coach B's rules  │
    │  - Coach A's runners│           │  - Coach B's runners│
    └──────────┬──────────┘           └──────────┬──────────┘
               │                                  │
               ▼                                  ▼
    ┌─────────────────────┐           ┌─────────────────────┐
    │  Runners A1, A2, A3 │           │  Runners B1, B2, B3 │
    │  (via WhatsApp)     │           │  (via WhatsApp)     │
    └─────────────────────┘           └─────────────────────┘
               │                                  │
               └──────────────┬───────────────────┘
                              ▼
                   ┌─────────────────────┐
                   │    GOOGLE SHEETS    │
                   │  (single workbook)  │
                   └─────────────────────┘
```

---

## 3. Tech Stack

| Component | Tool | Notes |
|---|---|---|
| Language | Python 3.11+ | Main language for all agent logic |
| LLM | OpenAI GPT-4o mini | Cheap, fast, good quality. Use `gpt-4o` for complex reasoning if needed |
| WhatsApp API | Wati (wati.io) | Fastest setup in India. Fallback: Interakt or AiSensy |
| Data layer | Google Sheets API v4 | `gspread` Python library |
| Hosting | Railway.app (MVP) | Single Python service, always-on |
| Scheduler | APScheduler (in-process) | For morning messages and daily digests |
| Payments | Razorpay | Webhook triggers runner onboarding |
| HTTP server | FastAPI | Lightweight, handles webhooks |
| Environment vars | python-dotenv | Secrets management |

### Python Dependencies
```
fastapi
uvicorn
openai
gspread
google-auth
apscheduler
razorpay
python-dotenv
httpx
```

---

## 4. Google Sheets Structure

**One workbook. Multiple tabs. One source of truth.**

Workbook name: `MainMission Platform`

---

### Tab 1: `Runners`

All runners across all coaches.

| Column | Type | Description |
|---|---|---|
| runner_id | string | Unique ID e.g. `RUN_001` |
| name | string | Runner's full name |
| phone | string | WhatsApp number with country code e.g. `+919876543210` |
| coach_id | string | e.g. `COACH_A` — links to coach config |
| race_goal | string | e.g. `Half Marathon`, `10K` |
| race_date | date | Target race date `YYYY-MM-DD` |
| weekly_days | number | Training days per week e.g. `4` |
| injuries | string | Known injuries or history e.g. `Left knee, ITB` |
| fitness_level | string | `Beginner`, `Intermediate`, `Advanced` |
| start_date | date | Program start date |
| status | string | `Active`, `Paused`, `Completed`, `Churned` |
| prompt_version | string | Which agent config version this runner uses e.g. `v1.2` |
| payment_status | string | `Paid`, `Trial`, `Expired` |
| monthly_fee | number | Amount in INR |
| onboarded | boolean | `TRUE` once onboarding flow is complete |
| notes | string | Freeform coach notes |

---

### Tab 2: `Training_Plans`

One row per runner per training day.

| Column | Type | Description |
|---|---|---|
| plan_id | string | Unique ID e.g. `PLAN_001` |
| runner_id | string | FK to Runners tab |
| date | date | Session date `YYYY-MM-DD` |
| day_type | string | `Run`, `Rest`, `Cross-train`, `Race` |
| session_type | string | `Easy`, `Tempo`, `Intervals`, `Long Run`, `Recovery` |
| distance_km | number | Target distance |
| duration_min | number | Target duration (optional) |
| intensity | string | `Zone 2`, `Threshold`, `VO2 Max`, `Easy` |
| rpe_target | string | e.g. `4-5 out of 10` |
| coach_notes | string | Raw coach notes for this session |
| sent | boolean | Whether morning message was sent |
| sent_at | datetime | Timestamp of send |
| completed | boolean | Whether runner confirmed completion |
| actual_distance | number | What runner actually ran |
| rpe_actual | number | Runner's reported effort |
| runner_feedback | string | Raw text feedback from runner |
| flags | string | `injury`, `missed`, `overtraining`, `great_session` |

---

### Tab 3: `Coach_Configs`

One row per coach. This is where the agent's "brain" lives per coach.

| Column | Type | Description |
|---|---|---|
| coach_id | string | Unique ID e.g. `COACH_A` |
| coach_name | string | Full name |
| coach_phone | string | WhatsApp number |
| active_prompt_version | string | e.g. `v1.2` — the live version |
| system_prompt_v1 | string (long) | Full system prompt version 1 |
| system_prompt_v1_date | date | When v1 was created |
| system_prompt_v2 | string (long) | Full system prompt version 2 |
| system_prompt_v2_date | date | When v2 was created |
| system_prompt_v3 | string (long) | And so on... |
| system_prompt_v3_date | date | |
| coaching_style | string | e.g. `Strict and data-driven`, `Warm and motivational` |
| escalation_rules | string | What situations must always go to this coach |
| status | string | `Active`, `Inactive` |

To get the active system prompt:
1. Read `active_prompt_version` for the coach (e.g. `v1.2`)
2. Read the column `system_prompt_v1.2` for that coach's row
3. Inject into the LLM call

---

### Tab 4: `Rules_And_Corrections`

The coach's corrections and rules — injected into every LLM prompt.

| Column | Type | Description |
|---|---|---|
| rule_id | string | Unique ID |
| coach_id | string | Which coach this rule belongs to |
| date_added | date | When rule was created |
| situation | string | What triggered the correction |
| wrong_response | string | What the agent said |
| correct_response | string | What it should have said |
| rule_derived | string | The generalised rule e.g. "Always recommend rest for joint pain" |
| status | string | `Active`, `Archived` |
| source | string | `coach_correction`, `coach_instruction`, `manual` |

The agent fetches all `Active` rules for a given `coach_id` and injects them into the prompt as:

```
RULES (always follow these):
- Always recommend rest for joint pain — never suggest modified training
- Use empathy first when a runner has missed 3+ sessions
- Never give specific nutrition advice — redirect to a nutritionist
```

---

### Tab 5: `Conversation_Log`

Every message in and out, for every runner.

| Column | Type | Description |
|---|---|---|
| log_id | string | Unique ID |
| timestamp | datetime | Message timestamp |
| runner_id | string | FK to Runners |
| coach_id | string | FK to Coaches |
| direction | string | `inbound` (runner→agent) or `outbound` (agent→runner) |
| message | string | Full message text |
| message_type | string | `workout`, `feedback`, `question`, `escalation`, `onboarding` |
| handled_by | string | `agent` or `coach` |
| escalated | boolean | Whether this was flagged to coach |
| escalation_reason | string | Why it was escalated |

---

### Tab 6: `Platform_Log`

Platform-level events — payments, onboarding, errors.

| Column | Type | Description |
|---|---|---|
| timestamp | datetime | Event timestamp |
| event_type | string | `payment`, `onboarding`, `error`, `coach_instruction` |
| runner_id | string | If applicable |
| coach_id | string | If applicable |
| details | string | Free text description |
| status | string | `success`, `failed`, `pending` |

---

## 5. Agent Logic — How It Works

### 5.1 Incoming Message Flow

Every incoming WhatsApp message hits the same webhook endpoint. The master agent handles routing.

```python
@app.post("/webhook")
async def handle_incoming(request: Request):
    data = await request.json()
    phone = data["phone"]
    message = data["message"]

    # Step 1: Identify sender
    sender = identify_sender(phone)
    # Returns: {type: "runner"|"coach"|"unknown", id: ..., coach_id: ...}

    if sender.type == "unknown":
        handle_unknown_sender(phone, message)

    elif sender.type == "runner":
        handle_runner_message(sender, message)

    elif sender.type == "coach":
        handle_coach_message(sender, message)
```

---

### 5.2 Runner Message Handler

```python
def handle_runner_message(runner, message):
    # 1. Load runner context from Sheets
    runner_data = sheets.get_runner(runner.id)
    todays_plan = sheets.get_todays_plan(runner.id)
    recent_messages = sheets.get_last_n_messages(runner.id, n=5)

    # 2. Load coach config
    coach_config = sheets.get_coach_config(runner.coach_id)
    system_prompt = coach_config.active_system_prompt
    active_rules = sheets.get_active_rules(runner.coach_id)

    # 3. Build full prompt
    full_prompt = build_runner_prompt(
        system_prompt=system_prompt,
        rules=active_rules,
        runner=runner_data,
        plan=todays_plan,
        history=recent_messages,
        incoming=message
    )

    # 4. Classify intent
    intent = classify_intent(message)
    # Returns: "feedback"|"question"|"injury_flag"|"missed_session"|"general"

    # 5. Check if escalation needed
    if should_escalate(intent, message, runner_data):
        notify_coach(runner.coach_id, runner, message, reason=intent)

    # 6. Generate response
    response = llm.complete(full_prompt)

    # 7. Send response via WhatsApp
    whatsapp.send(runner.phone, response)

    # 8. Log everything to Sheets
    sheets.log_conversation(runner.id, message, response, intent)
    sheets.update_plan_feedback(runner.id, message)
```

---

### 5.3 Coach Message Handler

```python
def handle_coach_message(coach, message):
    # Detect instruction type
    if is_correction(message):
        # "That response was wrong, you should have said..."
        handle_correction(coach, message)

    elif is_runner_specific_instruction(message):
        # "Tell Priya to take it easy tomorrow"
        handle_runner_instruction(coach, message)

    elif is_broadcast_instruction(message):
        # "Tell everyone long run is moved to Saturday"
        handle_broadcast(coach, message)

    elif is_query(message):
        # "Who hasn't completed this week?"
        handle_coach_query(coach, message)

    elif is_plan_update(message):
        # Coach sends updated plan or attaches file
        handle_plan_update(coach, message)
```

---

### 5.4 Escalation Rules

The agent auto-escalates to the coach when:

- Runner mentions pain/injury keywords: `pain`, `hurt`, `injury`, `sore`, `tight`, `pulled`, `swollen`, `twisted`
- Runner has missed 3+ consecutive sessions
- Runner sends a message expressing desire to quit or extreme frustration
- Runner asks a question the agent's confidence score is below threshold on
- Runner hasn't responded in 48 hours (checked by scheduler)

Escalation format sent to coach via WhatsApp:
```
⚠️ ESCALATION — Priya Sharma

Situation: Mentioned knee pain (3rd time this week)
Her message: "knee is really hurting today, been going on 3 days"
Agent response sent: [what agent said]

Action needed: Do you want to (1) Give her a rest day (2) Modify her plan (3) Refer to physio?
Reply 1, 2, or 3 — or type a custom instruction.
```

---

### 5.5 Morning Message Scheduler

Runs at 6:00am IST every day.

```python
@scheduler.scheduled_job('cron', hour=6, minute=0, timezone='Asia/Kolkata')
def send_morning_messages():
    active_runners = sheets.get_all_active_runners()

    for runner in active_runners:
        plan = sheets.get_todays_plan(runner.id)

        if plan.day_type == "Rest":
            message = generate_rest_day_message(runner)
        else:
            message = generate_workout_message(runner, plan)

        # Send as WhatsApp template message
        whatsapp.send_template(
            phone=runner.phone,
            template_name="daily_workout_prompt",
            variables={
                "runner_name": runner.name,
                "session_type": plan.session_type,
                "distance": plan.distance_km
            }
        )
        sheets.mark_plan_sent(plan.plan_id)
```

---

### 5.6 Evening Check-in Scheduler

Runs at 7:00pm IST. Checks for non-responders.

```python
@scheduler.scheduled_job('cron', hour=19, minute=0, timezone='Asia/Kolkata')
def evening_checkin():
    runners_no_response = sheets.get_runners_with_no_feedback_today()

    for runner in runners_no_response:
        whatsapp.send_template(
            phone=runner.phone,
            template_name="missed_session_checkin",
            variables={"runner_name": runner.name}
        )
```

---

### 5.7 Daily Digest to Coach

Runs at 9:00pm IST.

```python
@scheduler.scheduled_job('cron', hour=21, minute=0, timezone='Asia/Kolkata')
def send_coach_digest():
    for coach in sheets.get_all_active_coaches():
        runners = sheets.get_coach_runners(coach.id)
        todays_data = sheets.get_todays_summary(coach.id)

        digest = generate_digest(coach, runners, todays_data)
        # Format: "Today: 7/10 completed. 2 missed. 1 flagged (Priya - knee pain). Arjun had a great session."

        whatsapp.send_text(coach.phone, digest)
```

---

## 6. Prompt Architecture

### 6.1 Full Prompt Structure

Every LLM call is constructed as follows:

```
SYSTEM PROMPT (from Coach Config sheet)
↓
ACTIVE RULES (from Rules & Corrections sheet)
↓
RUNNER PROFILE (from Runners sheet)
↓
TODAY'S TRAINING PLAN (from Training Plans sheet)
↓
CONVERSATION HISTORY (last 5 messages from Conversation Log)
↓
INCOMING MESSAGE (what the runner just sent)
```

---

### 6.2 Example System Prompt (Coach A)

```
You are the AI coaching assistant for Main Mission, a running coaching platform in Bangalore, India.
You represent Coach [Name] and communicate with their runners on WhatsApp.

Your role:
- Deliver daily training instructions in a warm, motivating, personalised way
- Collect workout feedback and log it accurately
- Answer running-related questions confidently
- Flag concerns (injury, dropout risk, overtraining) to the coach
- Never replace the human coach — you support and amplify them

Tone: Warm but direct. Like a knowledgeable friend who runs, not a corporate chatbot.
Language: English with occasional Hindi words is fine (e.g. "chalo", "kya scene hai")
Length: Keep messages short — WhatsApp is a conversational medium. 2-4 sentences max unless explaining something technical.

What you NEVER do:
- Give specific nutrition or medical advice
- Promise race outcomes or specific time improvements
- Speak negatively about any competitor or other coach
- Share one runner's data with another runner

What you ALWAYS do:
- Use the runner's name
- Reference their specific race goal and timeline
- Reference what they told you yesterday if relevant
- End motivational messages with an emoji (one, not five)
```

---

### 6.3 Rules Injection Format

```
COACH RULES (always follow — these override your defaults):
1. Always recommend complete rest for any joint pain. Never suggest modified running.
2. When a runner misses 3+ sessions, lead with empathy before accountability.
3. Never suggest running in temperatures above 35°C — always suggest early morning or treadmill.
4. Priya has a history of ITB — always check in after long runs specifically about her left knee.
```

---

### 6.4 Runner Context Injection Format

```
RUNNER PROFILE:
Name: Priya Sharma
Race goal: Half Marathon (Bangalore Marathon, January 19)
Weeks to race: 11
Training days per week: 4 (Mon, Wed, Fri, Sun)
Fitness level: Intermediate
Known issues: Left knee (ITB history)
Current streak: 3 sessions completed in a row
Overall completion rate: 78%
```

---

### 6.5 Today's Plan Injection Format

```
TODAY'S SESSION:
Type: Easy Run
Distance: 6 km
Intensity: Zone 2 (conversational pace)
RPE target: 4-5 out of 10
Coach notes: Focus on form, not pace. This is a recovery run after yesterday's tempo.
```

---

## 7. WhatsApp Templates to Pre-approve with Meta

Submit these templates during BSP onboarding. They cover all proactive (business-initiated) messages.

### Template 1: `daily_workout_prompt`
```
Good morning {{1}}! Your {{2}} is ready for today.
Reply GO to get your full session details 🏃
```

### Template 2: `rest_day_message`
```
Good morning {{1}}! Today is a scheduled rest day.
Rest is where the gains happen. Reply READY if you're feeling good for tomorrow 💪
```

### Template 3: `missed_session_checkin`
```
Hey {{1}}, missed you on the roads today!
Rest day or life happened? Just reply and let me know 🙂
```

### Template 4: `weekly_summary`
```
{{1}}, here's your week in review:
✅ Sessions completed: {{2}}/{{3}}
📏 Total distance: {{4}} km
🗓 Weeks to race: {{5}}

Reply SUMMARY for the full breakdown.
```

### Template 5: `onboarding_welcome`
```
Welcome to Main Mission, {{1}}! 🏃
I'm your AI coaching assistant. Your coach {{2}} has set up your programme.
Reply HI to get started — I'll ask you a few quick questions to personalise your plan.
```

### Template 6: `coach_escalation`
```
⚠️ Action needed for {{1}}.
{{2}}
Reply to this message with your instruction.
```

---

## 8. Onboarding Flow

Triggered automatically when Razorpay webhook fires for a successful payment.

```
Payment confirmed
    ↓
Create runner row in Sheets (name, phone, payment_status=Paid, onboarded=FALSE)
    ↓
Send Template 5 (Welcome message)
    ↓
Runner replies "HI"
    ↓ 24-hour window opens
Agent runs onboarding conversation (free-form):
    Q1: "What race are you training for, and when is it?"
    Q2: "How many days a week can you train?"
    Q3: "Any injuries or niggles I should know about?"
    Q4: "Are you more of a morning or evening runner?"
    Q5: "What's your current weekly mileage roughly?"
    ↓
Agent updates runner row in Sheets with collected data
    ↓
Notify coach: "New runner onboarded: [name]. Profile attached. Please set up their training plan."
    ↓
Mark onboarded=TRUE
```

---

## 9. Version Control for Agent Config

### Updating the System Prompt

1. Coach WhatsApps agent: *"I want to update how you handle injury responses"*
2. Agent asks for the new instruction
3. Coach provides it
4. Agent creates a new version row in `Coach_Configs` sheet:
   - Copies current active prompt to new column (`system_prompt_v1.3`)
   - Appends the new instruction
   - Updates `active_prompt_version` to `v1.3`
   - Logs the change in `Platform_Log`
5. New prompt is live immediately for all this coach's runners

### Correcting a Mistake

1. Coach sends: *"That response to Priya was wrong. When someone says knee pain you should say rest, not easy run"*
2. Agent:
   - Logs to `Rules_And_Corrections` sheet with status=Active
   - Confirms to coach: *"Got it. Rule added: Always recommend rest for knee pain. Active immediately."*
3. On next LLM call, the rule is injected into the prompt

### Rolling Back

Coach sends: *"Go back to the previous version of the prompt"*
Agent:
- Reads version history from `Coach_Configs`
- Sets `active_prompt_version` to the previous version
- Confirms to coach

---

## 10. Razorpay Webhook

```python
@app.post("/razorpay/webhook")
async def razorpay_webhook(request: Request):
    data = await request.json()

    if data["event"] == "payment.captured":
        payment = data["payload"]["payment"]["entity"]

        # Extract runner details from payment notes
        runner_name = payment["notes"]["name"]
        runner_phone = payment["notes"]["phone"]
        coach_id = payment["notes"]["coach_id"]  # passed in payment link
        monthly_fee = payment["amount"] / 100  # paise to rupees

        # Create runner in Sheets
        sheets.create_runner({
            "name": runner_name,
            "phone": runner_phone,
            "coach_id": coach_id,
            "monthly_fee": monthly_fee,
            "payment_status": "Paid",
            "start_date": today(),
            "status": "Active",
            "onboarded": False
        })

        # Trigger onboarding
        coach = sheets.get_coach(coach_id)
        whatsapp.send_template(
            phone=runner_phone,
            template_name="onboarding_welcome",
            variables={"runner_name": runner_name, "coach_name": coach.name}
        )

        # Log
        sheets.log_platform_event("payment", runner_phone, coach_id, f"₹{monthly_fee} received")
```

---

## 11. File Structure

```
main_mission_agent/
│
├── main.py                    # FastAPI app, webhook endpoints
├── requirements.txt           # All dependencies
├── .env                       # Secrets (never commit)
├── .env.example               # Template for env vars
│
├── agents/
│   ├── master_agent.py        # Router, onboarding, platform logic
│   ├── coach_agent.py         # Per-coach message handling
│   └── prompts.py             # Prompt builder functions
│
├── integrations/
│   ├── whatsapp.py            # Wati/WhatsApp API wrapper
│   ├── sheets.py              # Google Sheets read/write wrapper
│   ├── llm.py                 # OpenAI API wrapper
│   └── razorpay.py            # Razorpay webhook handler
│
├── scheduler/
│   └── jobs.py                # Morning messages, digests, check-ins
│
├── utils/
│   ├── intent_classifier.py   # Classify incoming message intent
│   ├── escalation.py          # Escalation detection logic
│   └── helpers.py             # Date formatting, phone normalisation
│
└── config/
    └── settings.py            # Load env vars, constants
```

---

## 12. Environment Variables

```bash
# WhatsApp (Wati)
WATI_API_URL=https://live-server-xxxx.wati.io
WATI_API_TOKEN=your_wati_api_token

# OpenAI
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS_JSON=path/to/credentials.json
GOOGLE_SHEETS_WORKBOOK_ID=your_workbook_id

# Razorpay
RAZORPAY_KEY_ID=your_key
RAZORPAY_KEY_SECRET=your_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# App
APP_ENV=production
TIMEZONE=Asia/Kolkata
MORNING_MESSAGE_HOUR=6
EVENING_CHECKIN_HOUR=19
DIGEST_HOUR=21
```

---

## 13. Build Order — Week by Week

### Week 1: Foundation
- [ ] Set up FastAPI server on Railway
- [ ] Wati account setup + WhatsApp Business API connected
- [ ] Google Sheets workbook created with all tabs and columns
- [ ] Google Sheets API connected (`gspread`)
- [ ] Basic webhook receiver — logs all incoming messages to Sheets
- [ ] Basic outbound message sending — send a hardcoded reply
- **End of Week 1:** Messages flow in and out. Everything logs to Sheets.

### Week 2: Agent Intelligence
- [ ] LLM integration — OpenAI API connected
- [ ] Prompt builder — assembles full prompt from Sheets data
- [ ] Runner message handler — reads context, generates response, sends
- [ ] Intent classifier — feedback / question / injury / missed
- [ ] Escalation detection — flags to coach via WhatsApp
- [ ] Conversation logging — every exchange saved to Sheets
- **End of Week 2:** Agent responds intelligently to runner messages.

### Week 3: Scheduling + Coach Flow
- [ ] APScheduler setup — morning messages at 6am IST
- [ ] Template messages configured and approved in Wati
- [ ] Morning workout message flow — reads plan, sends template, logs
- [ ] Evening check-in — nudges non-responders
- [ ] Daily coach digest — 9pm summary to coach
- [ ] Coach message handler — corrections, instructions, queries
- [ ] Rules & Corrections flow — coach correction → Sheets → active in prompt
- **End of Week 3:** Full daily loop running automatically.

### Week 4: Onboarding + Payments + Multi-Coach
- [ ] Razorpay webhook — payment → runner created → welcome message
- [ ] Onboarding conversation flow — 5 questions, updates Sheets
- [ ] Multi-coach routing — master agent routes by coach_id
- [ ] Second coach config tab — independent prompt and rules
- [ ] Version control flow — coach can update prompt via WhatsApp
- [ ] End-to-end test with 2 coaches and 5 test runners
- **End of Week 4:** Production-ready. Onboard first paying runners.

---

## 14. Cost at Scale

| Component | 100 runners | 500 runners | 1,000 runners |
|---|---|---|---|
| Wati/BSP | ₹999 | ₹2,999 | ₹4,999 |
| Meta conversation charges | ₹700 | ₹3,500 | ₹7,000 |
| OpenAI (GPT-4o mini) | ₹250 | ₹1,250 | ₹2,500 |
| Railway hosting | ₹500 | ₹500 | ₹1,000 |
| **Total** | **₹2,449** | **₹8,249** | **₹15,499** |
| Revenue (₹1,000/runner) | ₹1,00,000 | ₹5,00,000 | ₹10,00,000 |
| **Infrastructure margin** | **97.5%** | **98.3%** | **98.4%** |

---

## 15. Key Constraints and Edge Cases

### WhatsApp 24-Hour Window Rule
- Any message YOU initiate (morning workout, digests, nudges) must use a pre-approved template
- Once a runner replies, you have 24 hours of free-form messaging
- If no reply in 24 hours, the next proactive message must be a template again
- Handle this in `whatsapp.py` — check last_runner_message timestamp before choosing template vs free-form

### Phone Number Format
- Always store and send with country code: `+919876543210`
- Normalise all incoming numbers on receipt — strip spaces, dashes, leading zeros

### Google Sheets Rate Limits
- Sheets API allows 300 requests per minute per project
- At 100 runners this is fine
- At 1,000+ runners: batch reads, cache runner data in memory for 60 seconds

### LLM Token Limits
- GPT-4o mini: 128k context window — more than enough
- Keep conversation history to last 10 messages max to control costs
- Full prompt should stay under 2,000 tokens for cost efficiency

### Timezone
- All scheduling in IST (`Asia/Kolkata`)
- Store all timestamps in IST in Sheets for coach readability
- Use `pytz` for timezone handling

---

*Technical specification — Main Mission Platform v1.0 — May 2026*
*Build the MVP first. Validate with real runners. Expand from there.*
