import hmac
import hashlib
from datetime import date
from config.settings import RAZORPAY_WEBHOOK_SECRET
from integrations.sheets import sheets
from integrations.whatsapp import whatsapp


async def razorpay_webhook(data: dict):
    if data.get("event") != "payment.captured":
        return

    payment = data["payload"]["payment"]["entity"]
    notes = payment.get("notes", {})

    runner_name = notes.get("name")
    runner_phone = notes.get("phone")
    coach_id = notes.get("coach_id")
    monthly_fee = payment["amount"] / 100  # paise to rupees

    runner_id = sheets.create_runner({
        "name": runner_name,
        "phone": runner_phone,
        "coach_id": coach_id,
        "monthly_fee": monthly_fee,
        "payment_status": "Paid",
        "start_date": date.today().isoformat(),
        "status": "Active",
    })

    coach = sheets.get_coach_config(coach_id)
    await whatsapp.send_template(
        phone=runner_phone,
        template_name="onboarding_welcome",
        variables={"runner_name": runner_name, "coach_name": coach["coach_name"]}
    )

    sheets.log_platform_event("payment", runner_id, coach_id, f"₹{monthly_fee} received")


def verify_signature(payload_body: bytes, signature: str) -> bool:
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode() if RAZORPAY_WEBHOOK_SECRET else b"",
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
