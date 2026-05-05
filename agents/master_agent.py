import logging

from integrations.sheets import sheets
from integrations.whatsapp import whatsapp
from agents.coach_agent import handle_runner_message, handle_coach_message
from agents.onboarding_agent import is_onboarding, start_onboarding, handle_onboarding

logger = logging.getLogger(__name__)


async def handle_incoming(data: dict):
    phone = data.get("waId") or data.get("phone")
    text = data.get("text", {})
    message = text.get("body", "") if isinstance(text, dict) else data.get("message", "")

    if not phone or not message:
        logger.debug("Skipping webhook event — no phone or message body")
        return

    normalized_phone = _normalize_phone(phone)
    sender = identify_sender(normalized_phone)

    logger.info(f"Incoming message from {normalized_phone} (type={sender['type']}): {message[:60]}")

    if sender["type"] == "runner":
        runner_data = sender["data"]
        if str(runner_data.get("onboarded", "TRUE")).upper() == "FALSE":
            if not is_onboarding(normalized_phone):
                start_onboarding(
                    normalized_phone,
                    sender["coach_id"],
                    name=runner_data.get("name", ""),
                    runner_id=sender["id"],
                )
            response = await handle_onboarding(normalized_phone, message)
            await whatsapp.send_text(runner_data["phone"], response)
        else:
            await handle_runner_message(sender, message)
    elif sender["type"] == "coach":
        await handle_coach_message(sender, message)
    else:
        await handle_unknown_sender(normalized_phone, message)


def identify_sender(phone: str) -> dict:
    runner = sheets.find_runner_by_phone(phone)
    if runner:
        return {"type": "runner", "id": runner["runner_id"], "coach_id": runner["coach_id"], "data": runner}

    coach = sheets.find_coach_by_phone(phone)
    if coach:
        return {"type": "coach", "id": coach["coach_id"], "data": coach}

    return {"type": "unknown", "phone": phone}


async def handle_unknown_sender(phone: str, message: str):
    await whatsapp.send_text(phone, "Hi! I don't have this number on file. Please contact Main Mission to get set up.")


def _normalize_phone(phone: str) -> str:
    phone = str(phone).strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone
