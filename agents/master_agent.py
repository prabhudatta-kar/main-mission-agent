import logging

from config.settings import DEFAULT_COACH_ID, SUPPORT_EMAIL
from integrations.firebase_db import sheets
from integrations.whatsapp import whatsapp
from agents.coach_agent import handle_runner_message, handle_coach_message, generate_runner_response, handle_runner_image, handle_runner_audio
from agents.onboarding_agent import is_onboarding, start_onboarding, handle_onboarding

logger = logging.getLogger(__name__)


async def handle_incoming(data: dict):
    """Real webhook entry point — routes and sends reply via WhatsApp."""
    # Skip messages sent BY the operator/bot (owner=True) to avoid infinite loops
    if data.get("owner", False):
        logger.debug("Skipping operator-sent message (owner=True)")
        return

    msg_type = data.get("type", "")
    phone    = data.get("waId") or data.get("phone")

    # Detect image-type messages — Wati may use "image", "picture", or put media in a "media" field
    is_image = (
        msg_type == "image"
        or bool(data.get("image"))
        or (isinstance(data.get("media"), dict) and data["media"].get("url"))
    )

    # Detect audio/voice note messages
    is_audio = msg_type in ("audio", "voice", "ptt")

    if is_image:
        logger.info(f"Image webhook detected — type='{msg_type}' payload={data}")
    elif is_audio:
        logger.info(f"Audio/voice webhook detected — type='{msg_type}'")
    elif msg_type not in ("text", "message", ""):
        logger.info(f"Unknown webhook type='{msg_type}' — full payload: {data}")
        if not phone:
            return

    # Wati sends text as a plain string; for image messages text is null
    text_field = data.get("text") or ""
    message    = text_field if isinstance(text_field, str) else (text_field.get("body", "") if text_field else "")

    # Allow empty message for image and audio — they carry media, not text
    if not phone or (not message and not is_image and not is_audio):
        logger.debug("Skipping webhook event — no phone or message body")
        return

    normalized = _normalize_phone(phone)
    sender = identify_sender(normalized)
    logger.info(f"Incoming from {normalized} (type={sender['type']}): {message[:60] or '[image]'}")

    if sender["type"] == "runner":
        runner_data = sender["data"]

        # Audio/voice note — transcribe immediately so both onboarding and
        # normal flow receive plain text; don't silently drop during onboarding
        if is_audio:
            audio_url = data.get("data", "") if isinstance(data.get("data"), str) else ""
            logger.info(f"Voice note: url={audio_url!r}")
            if not audio_url:
                return
            try:
                import httpx
                from config.settings import WATI_API_TOKEN as _TOK
                from integrations.llm import llm as _llm
                async with httpx.AsyncClient() as _c:
                    _r = await _c.get(audio_url, headers={"Authorization": f"Bearer {_TOK}"},
                                      timeout=30, follow_redirects=True)
                    _r.raise_for_status()
                    _mime = _r.headers.get("content-type", "audio/ogg").split(";")[0].strip()
                    transcript = await _llm.transcribe(_r.content, _mime)
            except Exception as e:
                logger.error(f"Voice note transcription failed for {normalized}: {e}")
                await whatsapp.send_text(normalized, "Couldn't hear that clearly. Could you type it instead?")
                return
            if not transcript:
                await whatsapp.send_text(normalized, "Couldn't hear that clearly. Could you type it instead?")
                return
            logger.info(f"Voice note transcribed for {normalized}: {transcript[:80]}")

            if str(runner_data.get("onboarded", "TRUE")).upper() == "TRUE":
                # Onboarded runner — full pipeline with [Voice note] log prefix
                from agents.coach_agent import generate_runner_response as _gen
                result = await _gen(sender, transcript,
                                    inbound_override=f"[Voice note] {transcript}")
                if result.get("response"):
                    await whatsapp.send_text(runner_data["phone"], result["response"])
                return
            else:
                # During onboarding — treat transcript as typed text and fall through
                message = transcript

        # Image message — Wati sends URL in data["data"], caption in data["text"]
        if is_image:
            image_url = data.get("data", "") if isinstance(data.get("data"), str) else ""
            caption   = message  # data["text"] already extracted as message above
            logger.info(f"Image message: url={image_url!r} caption={caption!r}")
            if image_url and str(runner_data.get("onboarded", "TRUE")).upper() == "TRUE":
                await handle_runner_image(sender, image_url, caption)
                return
            # No URL or during onboarding — fall through as text if caption exists
            if not caption:
                return

        if str(runner_data.get("onboarded", "TRUE")).upper() == "FALSE":
            response = await _run_onboarding(normalized, sender, message)
            await whatsapp.send_text(runner_data["phone"], response)
        elif runner_data.get("payment_status") == "Trial":
            from datetime import date as _date
            trial_end = runner_data.get("trial_end_date", "")
            if trial_end and _date.today().isoformat() <= trial_end:
                await handle_runner_message(sender, message)   # trial active — full access
            else:
                await _handle_trial_expired(runner_data, message)
        elif runner_data.get("payment_status", "Paid") == "Unpaid":
            await _handle_unpaid_runner(runner_data, message)
        else:
            await handle_runner_message(sender, message)

    elif sender["type"] == "coach":
        await handle_coach_message(sender, message)

    else:
        # New number — create a provisional runner and start onboarding immediately.
        # Payment link is sent at the end of onboarding via Razorpay API.
        coach_id  = DEFAULT_COACH_ID
        runner_id = sheets.create_runner({
            "name":           "New Runner",
            "phone":          normalized,
            "coach_id":       coach_id,
            "status":         "Pending",
            "payment_status": "Unpaid",
            "onboarded":      False,
        })
        runner_data = sheets.get_runner(runner_id)
        sender      = {"type": "runner", "id": runner_id, "coach_id": coach_id, "data": runner_data}
        response    = await _run_onboarding(normalized, sender, message)
        await whatsapp.send_text(normalized, response)


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


async def _handle_trial_expired(runner_data: dict, message: str):
    """Trial ended — send subscription link once, then stay silent on repeats."""
    phone     = runner_data.get("phone", "")
    runner_id = runner_data.get("runner_id", "")
    first     = (runner_data.get("name") or "there").split()[0]
    if first == "New": first = "there"

    # Update status so the link is only sent once
    sheets.update_runner(runner_id, {"payment_status": "Unpaid"})

    link = runner_data.get("payment_link", "")
    if not link:
        try:
            from integrations.razorpay import create_subscription
            link = await create_subscription(
                name=runner_data.get("name", "Runner"),
                phone=phone,
                coach_id=runner_data.get("coach_id", ""),
                runner_id=runner_id,
            )
            if link:
                sheets.update_runner(runner_id, {"payment_link": link})
        except Exception as e:
            logger.error(f"Razorpay link generation failed for {runner_id}: {e}")

    if link:
        msg = (
            f"Your 2-week trial has ended — hope the coaching has been useful! "
            f"To keep your plan going, complete your subscription here:\n{link}"
        )
    else:
        msg = (
            f"Your trial has ended. To continue, message us at {SUPPORT_EMAIL} "
            f"and we'll get you set up."
        )

    await whatsapp.send_text(phone, msg)
    sheets.log_platform_event("trial_expired", runner_id, runner_data.get("coach_id", ""),
                              f"Trial ended, subscription link sent")
    logger.info(f"Trial expired for {runner_id} — subscription link sent")


async def _handle_unpaid_runner(runner_data: dict, message: str):
    phone     = runner_data.get("phone", "")
    runner_id = runner_data.get("runner_id", "")
    link      = runner_data.get("payment_link", "")
    msg_upper = message.strip().upper()

    if msg_upper == "HELP":
        # Try stored link first, otherwise generate a new one
        if not link:
            try:
                from integrations.razorpay import create_subscription
                link = await create_subscription(
                    name=runner_data.get("name", "Runner"),
                    phone=phone,
                    coach_id=runner_data.get("coach_id", ""),
                    runner_id=runner_id,
                )
                if link:
                    sheets.update_runner(runner_id, {"payment_link": link})
            except Exception:
                pass

        if link:
            reply = f"Here's your payment link:\n{link}"
        else:
            reply = f"Having trouble generating your link right now. Email us at {SUPPORT_EMAIL} and we'll sort it out."

        await whatsapp.send_text(phone, reply)
        sheets.log_conversation(runner_id, runner_data.get("coach_id", ""), message, reply, "payment_help")
        return

    # For all other messages — only send the reminder once, then stay silent
    recent = sheets.get_last_n_messages(runner_id, n=20)
    already_reminded = any(
        m.get("direction") == "outbound" and m.get("message_type") in ("payment_reminder", "payment_help")
        for m in recent
    )
    if not already_reminded:
        reply = "To get started, complete your subscription payment using the link we sent. Type HELP if you need it resent."
        await whatsapp.send_text(phone, reply)
        sheets.log_conversation(runner_id, runner_data.get("coach_id", ""), message, reply, "payment_reminder")
    # If already reminded, stay silent — no reply needed for "okay", "ok", "hi" etc.


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
