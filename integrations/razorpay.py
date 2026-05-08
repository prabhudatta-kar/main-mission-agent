import hmac
import hashlib
import logging
from datetime import date

from config.settings import RAZORPAY_WEBHOOK_SECRET
from integrations.firebase_db import sheets
from integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)


async def razorpay_webhook(data: dict):
    event = data.get("event", "")
    logger.info(f"Razorpay webhook received: {event}")

    if event == "payment.captured":
        # Payment link flow
        await _handle_payment_captured(data)

    elif event == "subscription.activated":
        # Subscription first payment — trigger onboarding
        await _handle_subscription_activated(data)

    elif event in ("invoice.paid", "subscription.charged"):
        # Recurring renewal — update payment status
        await _handle_subscription_renewal(data)

    else:
        logger.debug(f"Ignoring Razorpay event: {event}")


async def _handle_payment_captured(data: dict):
    """One-time payment link flow."""
    try:
        payment = data["payload"]["payment"]["entity"]
        notes   = payment.get("notes", {})
        if isinstance(notes, list):   # Razorpay sends [] when no notes set
            notes = {}
        await _create_and_onboard(
            name=notes.get("name"),
            phone=notes.get("phone"),
            coach_id=notes.get("coach_id"),
            monthly_fee=payment.get("amount", 0) / 100,
            subscription_id=None,
        )
    except Exception as e:
        logger.error(f"Error handling payment.captured: {e}")


async def _handle_subscription_activated(data: dict):
    """Subscription activated (first payment made) — create runner and onboard."""
    try:
        payload      = data.get("payload", {})
        subscription = payload.get("subscription", {}).get("entity", {})
        payment      = payload.get("payment",      {}).get("entity", {})

        notes           = subscription.get("notes", {})
        if isinstance(notes, list):   # Razorpay sends [] when no notes set
            notes = {}
        subscription_id = subscription.get("id", "")
        monthly_fee     = payment.get("amount", 0) / 100

        # Notes may also be on the payment object if not set on subscription
        if not notes.get("name"):
            notes = payment.get("notes", {})
            if isinstance(notes, list):
                notes = {}

        await _create_and_onboard(
            name=notes.get("name"),
            phone=notes.get("phone"),
            coach_id=notes.get("coach_id"),
            monthly_fee=monthly_fee,
            subscription_id=subscription_id,
        )
    except Exception as e:
        logger.error(f"Error handling subscription.activated: {e}")


async def _handle_subscription_renewal(data: dict):
    """Recurring payment — update payment status, log event."""
    try:
        payload      = data.get("payload", {})
        subscription = payload.get("subscription", {}).get("entity", {})
        payment      = payload.get("payment",      {}).get("entity", {})

        sub_id      = subscription.get("id", "")
        monthly_fee = payment.get("amount", 0) / 100

        # Find runner by subscription_id if stored, otherwise just log
        logger.info(f"Subscription renewal received: sub={sub_id}, ₹{monthly_fee}")
        sheets.log_platform_event("renewal", "", "", f"Sub {sub_id} renewed ₹{monthly_fee}")
    except Exception as e:
        logger.error(f"Error handling subscription renewal: {e}")


async def _create_and_onboard(name, phone, coach_id, monthly_fee, subscription_id):
    """Shared logic: create runner in Firebase and send WhatsApp welcome."""
    if not name or not phone or not coach_id:
        logger.error(
            f"Missing required notes — name={name}, phone={phone}, coach_id={coach_id}. "
            f"Add these as 'notes' when creating the subscription link."
        )
        return

    # Avoid duplicate runners for the same phone
    existing = sheets.find_any_runner_by_phone(phone)
    if existing:
        logger.warning(f"Runner with phone {phone} already exists ({existing['runner_id']}). Skipping creation.")
        sheets.log_platform_event("duplicate_payment", existing["runner_id"], coach_id,
                                  f"Payment received but runner already exists")
        return

    runner_id = sheets.create_runner({
        "name":            name,
        "phone":           phone,
        "coach_id":        coach_id,
        "monthly_fee":     monthly_fee,
        "payment_status":  "Paid",
        "start_date":      date.today().isoformat(),
        "status":          "Active",
        "onboarded":       False,
        "notes":           f"subscription_id={subscription_id}" if subscription_id else "",
    })

    sheets.log_platform_event("payment", runner_id, coach_id,
                              f"₹{monthly_fee} received — runner created, awaiting inbound Hi")
    logger.info(f"Runner {runner_id} created and onboarding initiated for {phone}")


def verify_signature(payload_body: bytes, signature: str) -> bool:
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode() if RAZORPAY_WEBHOOK_SECRET else b"",
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
