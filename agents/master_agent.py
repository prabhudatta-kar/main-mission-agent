from integrations.sheets import sheets
from integrations.whatsapp import whatsapp
from agents.coach_agent import handle_runner_message, handle_coach_message


async def handle_incoming(data: dict):
    phone = data.get("waId") or data.get("phone")
    text = data.get("text", {})
    message = text.get("body", "") if isinstance(text, dict) else data.get("message", "")

    sender = identify_sender(phone)

    if sender["type"] == "unknown":
        await handle_unknown_sender(phone, message)
    elif sender["type"] == "runner":
        await handle_runner_message(sender, message)
    elif sender["type"] == "coach":
        await handle_coach_message(sender, message)


def identify_sender(phone: str) -> dict:
    normalized = _normalize_phone(phone)

    runner = sheets.find_runner_by_phone(normalized)
    if runner:
        return {"type": "runner", "id": runner["runner_id"], "coach_id": runner["coach_id"], "data": runner}

    coach = sheets.find_coach_by_phone(normalized)
    if coach:
        return {"type": "coach", "id": coach["coach_id"], "data": coach}

    return {"type": "unknown", "phone": normalized}


async def handle_unknown_sender(phone: str, message: str):
    await whatsapp.send_text(phone, "Hi! I don't have this number on file. Please contact Main Mission to get set up.")


def _normalize_phone(phone: str) -> str:
    phone = str(phone).strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone
