import json
import logging
from datetime import date, timedelta

from agents.coaching_kb import get_coaching_context
from agents.prompt_store import get_prompt
from agents.template_selector import _handle_plan_query, _handle_plan_change_request
from integrations.firebase_db import sheets
from integrations.llm import llm
from integrations.whatsapp import whatsapp
from utils.escalation import should_escalate, notify_coach
from utils.intent_classifier import classify_intent

logger = logging.getLogger(__name__)

# ── Conversation gating ────────────────────────────────────────────────────────

_CLOSERS = {
    "ok", "okay", "k", "kk", "thanks", "thank you", "thx", "ty",
    "got it", "cool", "alright", "sure", "great", "noted",
    "will do", "done", "fine", "sounds good", "perfect", "yep", "yup",
    "👍", "👌", "✅", "🙏", "roger", "understood", "noted",
}

_GREETINGS = {
    "hi", "hello", "hey", "hiya", "howdy", "sup", "yo",
    "good morning", "good evening", "good afternoon", "morning", "evening",
}


def _is_conversation_closer(message: str) -> bool:
    cleaned = message.strip().lower().rstrip("!.").strip()
    return cleaned in _CLOSERS


def _is_greeting(message: str) -> bool:
    cleaned = message.strip().lower().rstrip("!.,").strip()
    return cleaned in _GREETINGS


def _coach_recently_messaged(recent_messages: list, window_minutes: int = 30) -> bool:
    """True if coach has manual control and hasn't handed back to AI."""
    from datetime import datetime
    cutoff = datetime.now().timestamp() - window_minutes * 60
    for m in reversed(recent_messages):
        mtype     = m.get("message_type", "")
        direction = m.get("direction", "")
        if mtype == "coach_handback":
            return False
        if direction == "outbound" and mtype == "coach_direct":
            try:
                ts = datetime.strptime(m["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp()
                if ts >= cutoff:
                    return True
            except Exception:
                pass
            return False
        if direction == "outbound" and mtype not in ("coach_direct", "coach_takeover",
                                                      "payment_reminder", "payment_help"):
            return False
    return False


def _log_inbound_only(runner_id: str, coach_id: str, message: str):
    import uuid, pytz
    from datetime import datetime
    ts     = datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
    log_id = f"LOG_{str(uuid.uuid4())[:6].upper()}"
    sheets._col("conversations").document(log_id).set({
        "log_id":            log_id,
        "timestamp":         ts,
        "runner_id":         runner_id,
        "coach_id":          coach_id,
        "direction":         "inbound",
        "message":           message,
        "message_type":      "coach_takeover",
        "handled_by":        "coach",
        "escalated":         False,
        "escalation_reason": "",
    })


def _no_plan_response(runner_data: dict) -> str:
    first = (runner_data.get("name") or "").split()[0]
    if not first or first == "New":
        first = "there"
    return f"Hey {first} — your coach is putting together your plan. Should have it ready within 24 hours."


def _build_plan_context(runner_id: str, plan) -> str:
    """Return a detailed plan string for LLM context — never leaves the LLM guessing."""
    if plan and str(plan.get("day_type", "")).lower() != "rest":
        reps     = plan.get("reps", "")
        rep_dist = plan.get("rep_distance_m", "")
        dist     = plan.get("distance_km", "")
        duration = plan.get("duration_min", "")
        if reps and rep_dist:
            metric = f"{reps} × {rep_dist}m"
        elif dist and str(dist) not in ("0", ""):
            metric = f"{dist}km"
        elif duration and str(duration) not in ("0", ""):
            metric = f"{duration}min"
        else:
            metric = ""
        ctx = (
            f"TODAY'S SESSION: {plan.get('session_type', 'Run')} {metric} "
            f"at {plan.get('intensity', 'easy')} (RPE {plan.get('rpe_target', '')})"
        )
        if plan.get("coach_notes"):
            ctx += f"\nCoach notes: {plan['coach_notes']}"
        if plan.get("workout_notes"):
            ctx += f"\nWorkout notes: {plan['workout_notes']}"
        return ctx

    # Rest day or no plan — find next upcoming session so LLM doesn't invent one
    start    = (date.today() + timedelta(days=1)).isoformat()
    end      = (date.today() + timedelta(days=14)).isoformat()
    upcoming = [p for p in sheets.get_runner_plans(runner_id, from_date=start, to_date=end)
                if str(p.get("day_type", "")).lower() != "rest"]
    if upcoming:
        nxt = upcoming[0]
        dist = nxt.get("distance_km", "")
        return (
            f"Today is a rest day. "
            f"Next session: {nxt.get('date', '')} — "
            f"{nxt.get('session_type', 'Run')} {dist + 'km' if dist and str(dist) not in ('0','') else ''} "
            f"at {nxt.get('intensity', 'easy')}"
        )
    return "Today is a rest day. No upcoming sessions scheduled in the next 2 weeks."


async def _generate_llm_response(runner: dict, plan, history: list,
                                  message: str, intent: str) -> str:
    """
    Free-form LLM response — no template constraints.
    Only used when the 24h session window is open (always true for inbound messages).
    """
    runner_id = runner.get("runner_id", "")
    coach_id  = runner.get("coach_id", "")

    # ── System prompt: tone → KB → coach rules ─────────────────────────────────
    base_system  = get_prompt("coach_response_system") or get_prompt("creative_vars_system")
    coaching_kb  = get_coaching_context(intent, message)
    coach_rules  = sheets.get_active_rules(coach_id)
    rules_text   = "\n".join(
        f"- {r['rule_derived']}" for r in coach_rules if r.get("rule_derived")
    ) if coach_rules else ""

    system_msg = base_system
    if coaching_kb:
        system_msg += f"\n\n{coaching_kb}"
    if rules_text:
        system_msg += f"\n\nCOACH'S RULES — override everything above:\n{rules_text}"

    # Behavioural guardrails — always appended, not editable from Firebase
    system_msg += """

CONVERSATION RULES:
- Do not repeat advice or concerns from your previous message. If you already mentioned knee pain, hydration, or any specific tip, skip it this time unless the runner raises it again.
- If the runner asks about medication, supplements, injections, or anything medical — do not give an opinion. Say it's worth checking with their coach or doctor directly.
- When answering questions about nutrition, pacing, or training science, use the coaching context provided — do not default to generic internet advice.
- Keep replies to 2-3 sentences maximum. If the answer is one sentence, that is fine.
- NEVER create training plans, suggest specific workout schedules, or prescribe distances, durations, or paces from your own knowledge. The coach creates the plan — not you. If the runner asks for a plan or workout and none exists in the data above, say: their coach will set one up within 24 hours and they can message the coach directly if they need it sooner."""


    # ── Runner context ─────────────────────────────────────────────────────────
    try:
        delta        = (date.fromisoformat(str(runner["race_date"])) - date.today()).days
        weeks_to_race = f"{max(0, delta // 7)} weeks"
    except Exception:
        weeks_to_race = "unknown"

    runner_ctx = (
        f"Runner: {runner.get('name')}, {runner.get('fitness_level', 'intermediate')} level\n"
        f"Race goal: {runner.get('race_goal', '')} on {runner.get('race_date', '')} ({weeks_to_race} away)\n"
        f"Training days/week: {runner.get('weekly_days', '')}\n"
        f"Known injuries/notes: {runner.get('injuries') or 'none reported'}"
    )

    # ── Plan context (planned + actuals if runner sent workout image) ──────────
    plan_ctx = _build_plan_context(runner_id, plan)
    if plan and plan.get("actual_summary"):
        plan_ctx += f"\n\nACTUAL WORKOUT (from runner's image): {plan['actual_summary']}"

    # ── Runner memory (long-term context) ──────────────────────────────────────
    memory     = runner.get("_memory", {})
    memory_ctx = ""
    if memory:
        parts = []
        if memory.get("summary"):      parts.append(f"Background: {memory['summary']}")
        if memory.get("known_issues"): parts.append(f"Known issues: {memory['known_issues']}")
        if memory.get("recent_form"):  parts.append(f"Recent form: {memory['recent_form']}")
        if memory.get("watch_points"): parts.append(f"Watch: {memory['watch_points']}")
        memory_ctx = "\n".join(parts)

    # ── Conversation history ───────────────────────────────────────────────────
    history_lines = []
    for m in history[-8:]:
        text = (m.get("message") or "").strip()
        if not text:
            continue
        role = "Runner" if m.get("direction") == "inbound" else "Coach"
        history_lines.append(f"{role}: {text}")

    # ── Assemble user message ──────────────────────────────────────────────────
    user_parts = [runner_ctx, plan_ctx]
    if memory_ctx:
        user_parts.append(f"Runner memory:\n{memory_ctx}")
    if history_lines:
        user_parts.append("Recent conversation:\n" + "\n".join(history_lines))
    user_parts.append(f"Runner: {message}")
    user_msg = "\n\n".join(filter(None, user_parts))

    try:
        return await llm.complete([
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ], max_tokens=300)
    except Exception as e:
        logger.error(f"LLM response failed for {runner_id}: {e}")
        return "Let me flag this for your coach — they'll get back to you shortly."


async def generate_runner_response(sender: dict, message: str) -> dict:
    runner_id   = sender["id"]
    coach_id    = sender["coach_id"]
    runner_data = sheets.get_runner(runner_id) or sender.get("data", {})

    all_plans   = sheets.get_runner_plans(runner_id)
    todays_plan = sheets.get_todays_plan(runner_id)
    memory      = sheets.get_runner_memory(runner_id) or {}
    recent_msgs = sheets.get_last_n_messages(runner_id, n=10)

    if memory:
        runner_data = {**runner_data, "_memory": memory}

    # Coach takeover — stay silent
    if _coach_recently_messaged(recent_msgs):
        logger.info(f"Coach takeover active for {runner_id} — AI staying silent")
        _log_inbound_only(runner_id, coach_id, message)
        return {"response": "", "intent": "coach_takeover"}

    # No plan yet — guard training-specific intents
    if not all_plans:
        intent = classify_intent(message)
        if intent in ("feedback", "missed_session"):
            response = _no_plan_response(runner_data)
            sheets.log_conversation(runner_id, coach_id, message, response, "awaiting_plan")
            return {"response": response, "intent": "awaiting_plan"}

    # Conversation closer — don't reply, avoid the "Ok" spam loop
    if _is_conversation_closer(message):
        sheets.log_conversation(runner_id, coach_id, message, "", "conversation_close")
        return {"response": "", "intent": "conversation_close"}

    # Bare greeting — respond naturally, don't dump plan data
    if _is_greeting(message):
        response = "Hey! What's on your mind?"
        sheets.log_conversation(runner_id, coach_id, message, response, "greeting")
        return {"response": response, "intent": "greeting"}

    intent = classify_intent(message)

    # Race update — dedicated handler
    if intent == "race_update":
        response = await _handle_race_update(runner_id, runner_data, message)
        sheets.log_conversation(runner_id, coach_id, message, response, intent)
        return {"response": response, "intent": intent}

    # Plan intents — fetch real data, no LLM hallucination
    if intent == "plan_query":
        response = await _handle_plan_query(runner_data, todays_plan, message)
        sheets.log_conversation(runner_id, coach_id, message, response, intent)
        return {"response": response, "intent": intent}

    if intent in ("plan_reschedule", "plan_tweak"):
        rtype    = "reschedule" if intent == "plan_reschedule" else "tweak"
        response = await _handle_plan_change_request(runner_data, todays_plan, message, rtype)
        sheets.log_conversation(runner_id, coach_id, message, response, intent)
        return {"response": response, "intent": intent}

    # Everything else — free-form LLM response (24h window always open for inbound)
    response = await _generate_llm_response(runner_data, todays_plan, recent_msgs, message, intent)

    sheets.log_conversation(runner_id, coach_id, message, response, intent)
    sheets.update_plan_feedback(runner_id, message)

    return {"response": response, "intent": intent}


async def _handle_race_update(runner_id: str, runner_data: dict, message: str) -> str:
    try:
        raw = await llm.complete([
            {"role": "system", "content": "Extract the race name and distance from the runner's message. Return only valid JSON."},
            {"role": "user",   "content": f"""Message: "{message}"

Return JSON:
{{"race_name": "name of the race mentioned", "distance": "distance if mentioned e.g. 42.2km, 21.1km, 10km — empty string if not mentioned"}}"""},
        ])
        raw  = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        race_name = data.get("race_name", "").strip()
        distance  = data.get("distance", "").strip()

        if not race_name:
            return "Which race did you sign up for? Let me add it to your schedule."

        from integrations.race_lookup import lookup_race
        race = await lookup_race(race_name)
        if race:
            name      = race.get("name", race_name)
            race_date = race.get("date", "")
            distances = race.get("distances", [])
            if not distance and len(distances) > 1:
                opts = " / ".join(distances[:4])
                return f"Nice, {name}! Which distance are you targeting — {opts}?"
            distance = distance or (distances[0] if distances else "")
            sheets.add_runner_race(runner_id, name, race_date, distance)
            date_str = f" on {race_date}" if race_date else ""
            dist_str = f" {distance}" if distance else ""
            return f"Added {name}{dist_str}{date_str} to your race schedule. Your plan will account for both races."
        else:
            return f"I've noted that you've signed up for {race_name}. Could you confirm the date so I can update your schedule?"

    except Exception as e:
        logger.error(f"Race update handling failed: {e}")
        return "Tell me more about the race you signed up for and I'll add it to your schedule."


async def handle_runner_image(sender: dict, image_url: str, caption: str = ""):
    """
    Runner sent an image (workout screenshot, Garmin/Strava/Apple Watch, etc.).
    Downloads from Wati URL, sends to GPT-4o vision, extracts stats + replies naturally.
    """
    import base64
    import httpx
    from config.settings import WATI_API_TOKEN

    runner_id   = sender["id"]
    coach_id    = sender["coach_id"]
    runner_data = sheets.get_runner(runner_id) or sender.get("data", {})
    phone       = runner_data.get("phone", "")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                image_url,
                headers={"Authorization": f"Bearer {WATI_API_TOKEN}"},
                timeout=20,
                follow_redirects=True,
            )
            resp.raise_for_status()
            mime_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            image_b64 = base64.b64encode(resp.content).decode()
    except Exception as e:
        logger.error(f"Failed to download image {image_url} for {runner_id}: {e}")
        await whatsapp.send_text(phone, "Got your image but couldn't read it — can you share the key stats as text?")
        return

    first = (runner_data.get("name") or "there").split()[0]
    race  = runner_data.get("race_goal", "")

    system = (
        "You are a running coach receiving a workout screenshot from a runner on WhatsApp. "
        "Extract ALL stats visible in the image — whatever the app shows. Do not limit yourself "
        "to a fixed set of fields; use natural key names for everything you can read. "
        "Return ONLY valid JSON with exactly three keys:\n"
        "  'response': 1-2 sentence coaching reply using the specific numbers you extracted "
        "(plain text, no opener with runner's name, no generic advice)\n"
        "  'stats': object of every metric you can read from the image — distance, pace, HR, "
        "splits, zones, elevation, cadence, power, calories, app name, etc.\n"
        "  'summary': 2-3 sentences in plain English covering ALL extracted numbers — "
        "distance, pace, HR, splits, zones, anything visible. Be specific with numbers. "
        "This is stored as context for follow-up questions so completeness matters more than brevity."
    )
    text_prompt = (
        f"Runner: {first}" +
        (f", training for {race}" if race else "") +
        (f". Runner's caption: \"{caption}\"" if caption else "") +
        ". Extract everything visible and write the coaching reply."
    )

    response = ""
    stats: dict = {}
    summary = ""
    try:
        raw = await llm.complete_with_image(system, text_prompt, image_b64, mime_type, max_tokens=2000)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed   = json.loads(raw)
            response = parsed.get("response", "")
            stats    = parsed.get("stats", {})
            summary  = parsed.get("summary", "")
        except json.JSONDecodeError as je:
            logger.warning(f"Vision JSON truncated for {runner_id} ({je}) — extracting response field")
            # JSON truncated mid-string — pull the response value before the cut
            import re
            m = re.search(r'"response"\s*:\s*"((?:[^"\\]|\\.)*)', raw)
            if m:
                response = m.group(1).replace('\\"', '"').replace('\\n', '\n').rstrip('\\')
            # Try to get whatever stats came through before truncation
            ms = re.search(r'"stats"\s*:\s*(\{[^}]*)', raw)
            if ms:
                try:
                    stats = json.loads(ms.group(1) + "}")
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Vision call failed for {runner_id}: {e}")

    if not response:
        response = "Solid effort — I can see the stats. If you want me to compare against your plan, let me know what the key numbers were."

    # Attach actuals to the matching training plan
    plan = sheets.get_todays_plan(runner_id) or sheets.get_recent_sent_plan(runner_id)
    if plan and str(plan.get("day_type", "")).lower() != "rest":
        plan_id = plan.get("plan_id") or plan.get("_id", "")
        if plan_id:
            stats["image_url"] = image_url
            stats["summary"]   = summary
            sheets.update_plan_actuals(plan_id, stats)
            logger.info(f"Actuals written to plan {plan_id} for runner {runner_id}")

    # Store the full stats summary as the inbound message so follow-up questions
    # have the extracted data in conversation history and can answer precisely
    inbound_text = caption or ""
    if summary:
        inbound_text = f"[Workout image] {caption}\n\nExtracted stats: {summary}" if caption else f"[Workout image] {summary}"

    sheets.log_conversation(
        runner_id, coach_id,
        inbound=inbound_text or "[image]",
        outbound=response,
        intent="image_upload",
        media_id=image_url,
        media_type="image",
    )

    await whatsapp.send_text(phone, response)
    logger.info(f"Image processed for {runner_id}")


async def handle_runner_message(sender: dict, message: str):
    """Full runner pipeline including WhatsApp send and escalation check."""
    result = await generate_runner_response(sender, message)
    if not result["response"]:
        return

    runner_data = sender["data"]

    if should_escalate(result["intent"], message, runner_data):
        await notify_coach(sender["coach_id"], runner_data, message, reason=result["intent"])

    await whatsapp.send_text(runner_data["phone"], result["response"])


async def handle_coach_message(sender: dict, message: str):
    coach_id  = sender["id"]
    msg_lower = message.lower()

    if "was wrong" in msg_lower or "should have said" in msg_lower or "don't say" in msg_lower:
        await _handle_correction(coach_id, message)
    elif "tell everyone" in msg_lower or "tell all" in msg_lower:
        await _handle_broadcast(coach_id, message)
    elif any(word in msg_lower for word in ["who", "how many", "list", "show me"]):
        await _handle_coach_query(coach_id, message)
    else:
        await _handle_runner_instruction(coach_id, message)


async def _handle_correction(coach_id: str, message: str):
    rule = _extract_rule(message)
    sheets.add_rule(coach_id, rule, source="coach_correction", raw_message=message)
    coach = sheets.get_coach_config(coach_id)
    await whatsapp.send_text(coach["coach_phone"], f"Got it. Rule added: {rule}. Active immediately.")


async def _handle_broadcast(coach_id: str, message: str):
    runners = sheets.get_coach_runners(coach_id)
    for runner in runners:
        await whatsapp.send_text(runner["phone"], message)
    coach = sheets.get_coach_config(coach_id)
    await whatsapp.send_text(coach["coach_phone"], f"Broadcast sent to {len(runners)} runners.")


async def _handle_coach_query(coach_id: str, message: str):
    summary = sheets.get_todays_summary(coach_id)
    coach   = sheets.get_coach_config(coach_id)
    reply   = f"Today: {summary['completed']}/{summary['total']} completed. {len(summary['flagged'])} flagged."
    await whatsapp.send_text(coach["coach_phone"], reply)


async def _handle_runner_instruction(coach_id: str, message: str):
    coach = sheets.get_coach_config(coach_id)
    await whatsapp.send_text(coach["coach_phone"], f"Noted. I'll apply this: {message}")
    sheets.add_rule(coach_id, message, source="coach_instruction", raw_message=message)


def _extract_rule(message: str) -> str:
    if "should have said" in message:
        return message.split("should have said")[-1].strip()
    if "don't say" in message:
        return "Do not say: " + message.split("don't say")[-1].strip()
    return message
