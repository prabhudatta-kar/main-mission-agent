import logging

from integrations.firebase_db import sheets
from integrations.whatsapp import whatsapp
from integrations.llm import llm
from agents.prompts import build_runner_prompt
from agents.template_selector import select_template_response
from utils.intent_classifier import classify_intent
from utils.escalation import should_escalate, notify_coach

logger = logging.getLogger(__name__)


def _coach_recently_messaged(recent_messages: list, window_minutes: int = 30) -> bool:
    """True if the coach sent a manual message within the last window_minutes."""
    from datetime import datetime
    cutoff = (datetime.now().timestamp() - window_minutes * 60)
    for m in reversed(recent_messages):
        if m.get("direction") != "outbound":
            continue
        if m.get("message_type") == "coach_direct":
            try:
                ts = datetime.strptime(m["timestamp"], "%Y-%m-%d %H:%M:%S").timestamp()
                if ts >= cutoff:
                    return True
            except Exception:
                pass
        # Any inbound message resets the takeover (runner was already chatting with AI)
        if m.get("direction") == "inbound":
            return False
    return False


def _log_inbound_only(runner_id: str, coach_id: str, message: str):
    """Log the runner's inbound message without creating an outbound record."""
    import uuid
    from datetime import datetime
    import pytz
    ts = datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")
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


async def generate_runner_response(sender: dict, message: str) -> dict:
    """
    Runs the full runner pipeline and returns {response, intent}.
    Uses template selection — picks an approved template and fills variables.
    Does NOT send to WhatsApp — caller decides what to do with the response.
    """
    runner_id = sender["id"]
    coach_id  = sender["coach_id"]

    runner_data = sheets.get_runner(runner_id) or sender.get("data", {})

    # Guard: if no plan exists yet, only answer general questions.
    # Training-specific intents (feedback, missed session, workout detail) need a plan to make sense.
    all_plans = sheets.get_runner_plans(runner_id)
    if not all_plans:
        intent = classify_intent(message)
        if intent in ("feedback", "missed_session", "workout", "checkin"):
            response = _no_plan_response(runner_data)
            sheets.log_conversation(runner_id, coach_id, message, response, "awaiting_plan")
            return {"response": response, "intent": "awaiting_plan"}
        # General questions (injury advice, nutrition, gear, etc.) — answer them

    todays_plan = sheets.get_todays_plan(runner_id)

    # Use compact memory for long-term context + only last 5 messages for current thread
    memory          = sheets.get_runner_memory(runner_id) or {}
    recent_messages = sheets.get_last_n_messages(runner_id, n=5)

    # Merge memory into runner_data so template selector can use it
    if memory:
        runner_data = {**runner_data, "_memory": memory}

    # Coach takeover: if coach sent a manual message in the last 30 min, stay silent
    if _coach_recently_messaged(recent_messages):
        logger.info(f"Coach takeover active for {runner_id} — AI staying silent")
        _log_inbound_only(runner_id, coach_id, message)
        return {"response": "", "intent": "coach_takeover"}

    intent = classify_intent(message)

    if intent == "race_update":
        response = await _handle_race_update(runner_id, runner_data, message)
        sheets.log_conversation(runner_id, coach_id, message, response, intent)
        return {"response": response, "intent": intent}

    response = await select_template_response(
        runner=runner_data,
        plan=todays_plan,
        history=recent_messages,
        message=message,
        intent=intent,
    )

    sheets.log_conversation(runner_id, coach_id, message, response, intent)
    sheets.update_plan_feedback(runner_id, message)

    return {"response": response, "intent": intent}


async def _handle_race_update(runner_id: str, runner_data: dict, message: str) -> str:
    """Detect the new race from the message, look it up, and add it to the runner's profile."""
    first = (runner_data.get("name") or "there").split()[0]
    if first == "New":
        first = "there"

    try:
        from integrations.race_lookup import lookup_race
        from integrations.llm import llm as _llm
        import json as _json

        # Ask LLM to extract race name and distance from the message
        raw = await _llm.complete([
            {"role": "system", "content": "Extract the race name and distance from the runner's message. Return only valid JSON."},
            {"role": "user", "content": f"""Message: "{message}"

Return JSON:
{{"race_name": "name of the race mentioned", "distance": "distance if mentioned e.g. 42.2km, 21.1km, 10km — empty string if not mentioned"}}"""},
        ])
        raw  = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = _json.loads(raw)
        race_name = data.get("race_name", "").strip()
        distance  = data.get("distance", "").strip()

        if not race_name:
            return f"Which race did you sign up for? Let me add it to your schedule."

        race = await lookup_race(race_name)
        if race:
            name = race.get("name", race_name)
            date = race.get("date", "")
            distances = race.get("distances", [])

            # If distance not mentioned and race has multiple, ask
            if not distance and len(distances) > 1:
                opts = " / ".join(distances[:4])
                return f"Nice, {name}! Which distance are you targeting — {opts}?"

            distance = distance or (distances[0] if distances else "")
            sheets.add_runner_race(runner_id, name, date, distance)

            date_str = f" on {date}" if date else ""
            dist_str = f" {distance}" if distance else ""
            return f"Added {name}{dist_str}{date_str} to your race schedule. Your plan will account for both races."
        else:
            return f"I've noted that you've signed up for {race_name}. Could you confirm the date so I can update your schedule?"

    except Exception as e:
        logger.error(f"Race update handling failed: {e}")
        return f"Tell me more about the race you signed up for and I'll add it to your schedule."


async def handle_runner_message(sender: dict, message: str):
    """Full runner pipeline including WhatsApp send and escalation check."""
    result = await generate_runner_response(sender, message)
    if not result["response"]:
        return   # coach takeover or awaiting plan — stay silent

    runner_data = sender["data"]

    if should_escalate(result["intent"], message, runner_data):
        await notify_coach(sender["coach_id"], runner_data, message, reason=result["intent"])

    await whatsapp.send_text(runner_data["phone"], result["response"])


async def handle_coach_message(sender: dict, message: str):
    coach_id = sender["id"]
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
    coach = sheets.get_coach_config(coach_id)
    reply = f"Today: {summary['completed']}/{summary['total']} completed. {len(summary['flagged'])} flagged."
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
