import logging

from integrations.firebase_db import sheets
from integrations.whatsapp import whatsapp
from agents.coach_agent import handle_runner_message, handle_coach_message, generate_runner_response
from agents.onboarding_agent import is_onboarding, start_onboarding, handle_onboarding

logger = logging.getLogger(__name__)


async def handle_incoming(data: dict):
    """Real webhook entry point — routes and sends reply via WhatsApp."""
    # Skip messages sent BY the operator/bot (owner=True) to avoid infinite loops
    if data.get("owner", False):
        logger.debug("Skipping operator-sent message (owner=True)")
        return

    phone = data.get("waId") or data.get("phone")

    # Wati sends text as a plain string (not {"body": ...})
    text_field = data.get("text", "")
    message = text_field if isinstance(text_field, str) else text_field.get("body", "")

    if not phone or not message:
        logger.debug("Skipping webhook event — no phone or message body")
        return

    normalized = _normalize_phone(phone)
    sender = identify_sender(normalized)
    logger.info(f"Incoming from {normalized} (type={sender['type']}): {message[:60]}")

    if sender["type"] == "runner":
        runner_data = sender["data"]
        if str(runner_data.get("onboarded", "TRUE")).upper() == "FALSE":
            response = await _run_onboarding(normalized, sender, message)
            await whatsapp.send_text(runner_data["phone"], response)
        else:
            await handle_runner_message(sender, message)

    elif sender["type"] == "coach":
        await handle_coach_message(sender, message)

    else:
        await whatsapp.send_text(
            normalized,
            "Hi! I don't have this number on file. Please contact Main Mission to get set up.",
        )


async def compute_response(phone: str, message: str, coach_id: str = None, name: str = None) -> dict:
    """
    Test UI entry point — same routing as handle_incoming but returns a dict instead of sending via WhatsApp.
    Single source of routing truth.
    """
    sender = identify_sender(phone)

    if sender["type"] == "runner":
        runner_data = sender["data"]
        if str(runner_data.get("onboarded", "TRUE")).upper() == "FALSE":
            response = await _run_onboarding(phone, sender, message)
            return {"sender_type": "onboarding", "intent": None, "response": response}
        else:
            result = await generate_runner_response(sender, message)
            return {"sender_type": "runner", "intent": result["intent"], "response": result["response"]}

    elif sender["type"] == "coach":
        return {"sender_type": "coach", "intent": None, "response": "Coach flow not simulated in test UI."}

    else:
        if not coach_id:
            return {
                "sender_type": "unknown",
                "intent": None,
                "response": "Select a coach from the panel above to start onboarding this number.",
            }
        response = await _run_onboarding(phone, {"coach_id": coach_id, "id": None}, message, name=name)
        return {"sender_type": "onboarding", "intent": None, "response": response}


async def _run_onboarding(phone: str, sender: dict, message: str, name: str = None) -> str:
    """Shared onboarding logic for both handle_incoming and compute_response."""
    if not is_onboarding(phone):
        runner_data = sender.get("data") or {}
        prefilled = {k: v for k, v in {
            "race": runner_data.get("race_goal"),
            "weekly_days": runner_data.get("weekly_days"),
            "injuries": runner_data.get("injuries"),
        }.items() if v}
        start_onboarding(
            phone,
            sender["coach_id"],
            name=name or runner_data.get("name", "New Runner"),
            runner_id=sender.get("id"),
            prefilled=prefilled,
        )
    return await handle_onboarding(phone, message)


def identify_sender(phone: str) -> dict:
    """
    Look up the sender in Sheets. Checks ALL runner rows (any status, any onboarded flag)
    so a returning runner is never mistaken for an unknown number.
    """
    runner = sheets.find_any_runner_by_phone(phone)
    if runner:
        return {"type": "runner", "id": runner["runner_id"], "coach_id": runner["coach_id"], "data": runner}

    coach = sheets.find_coach_by_phone(phone)
    if coach:
        return {"type": "coach", "id": coach["coach_id"], "data": coach}

    return {"type": "unknown", "phone": phone}


def _normalize_phone(phone: str) -> str:
    phone = str(phone).strip().replace(" ", "").replace("-", "").lstrip("0")
    if phone.startswith("+"):
        return phone
    if len(phone) == 10:
        return "+91" + phone
    if len(phone) == 12 and phone.startswith("91"):
        return "+" + phone
    return "+" + phone
