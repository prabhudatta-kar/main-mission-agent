from integrations.sheets import sheets
from integrations.whatsapp import whatsapp
from integrations.llm import llm
from agents.prompts import build_runner_prompt
from agents.template_selector import select_template_response
from utils.intent_classifier import classify_intent
from utils.escalation import should_escalate, notify_coach


async def generate_runner_response(sender: dict, message: str) -> dict:
    """
    Runs the full runner pipeline and returns {response, intent}.
    Uses template selection — picks an approved template and fills variables.
    Does NOT send to WhatsApp — caller decides what to do with the response.
    """
    runner_id = sender["id"]
    coach_id = sender["coach_id"]

    runner_data = sheets.get_runner(runner_id) or sender.get("data", {})
    todays_plan = sheets.get_todays_plan(runner_id)
    recent_messages = sheets.get_last_n_messages(runner_id, n=15)

    intent = classify_intent(message)
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


async def handle_runner_message(sender: dict, message: str):
    """Full runner pipeline including WhatsApp send and escalation check."""
    result = await generate_runner_response(sender, message)
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
