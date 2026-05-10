import hmac
import hashlib
import logging
from datetime import date

import httpx

from config.settings import APP_URL, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_PLAN_ID, RAZORPAY_WEBHOOK_SECRET
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
    """
    Subscription activated — runner already exists in Firebase (created during onboarding).
    Just mark them as paid and active.
    """
    try:
        payload      = data.get("payload", {})
        subscription = payload.get("subscription", {}).get("entity", {})

        notes = subscription.get("notes", {})
        if isinstance(notes, list):
            notes = {}

        runner_id       = notes.get("runner_id", "")
        subscription_id = subscription.get("id", "")

        runner    = None
        phone_for_msg = notes.get("whatsapp_number") or notes.get("phone", "")

        if runner_id:
            sheets.update_runner(runner_id, {
                "payment_status": "Paid",
                "status":         "Active",
                "notes":          f"subscription_id={subscription_id}",
            })
            sheets.log_platform_event("payment", runner_id, notes.get("coach_id", ""),
                                      f"Subscription activated: {subscription_id}")
            runner = sheets.get_runner(runner_id)
            logger.info(f"Runner {runner_id} marked Active after subscription.activated")
        else:
            # Fallback: find by phone stored in notes
            if phone_for_msg:
                existing = sheets.find_any_runner_by_phone(phone_for_msg)
                if existing:
                    sheets.update_runner(existing["runner_id"], {
                        "payment_status": "Paid",
                        "status":         "Active",
                        "notes":          f"subscription_id={subscription_id}",
                    })
                    runner = existing
                    logger.info(f"Runner {existing['runner_id']} marked Active by phone lookup")
                else:
                    logger.error(f"subscription.activated: no runner found for phone {phone_for_msg}")
            else:
                logger.error(f"subscription.activated: no runner_id or phone in notes: {notes}")

        if runner:
            await _send_payment_confirmation(runner)

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


async def _send_payment_confirmation(runner: dict):
    """Send a WhatsApp confirmation after subscription is activated."""
    phone = runner.get("phone", "")
    first = (runner.get("name") or "there").split()[0]
    if first == "New":
        first = "there"   # avoid "New Runner" placeholder leaking

    msg = (
        f"Payment done, {first} — you're in. "
        f"Coach will have your plan ready within 24 hours. "
        f"Message here anytime if you have questions."
    )

    # Prefer free-form text if within 24h session window, otherwise log a warning
    # (payment usually happens minutes after onboarding, so session should be open)
    if sheets.is_within_session_window(runner.get("runner_id", "")):
        await whatsapp.send_text(phone, msg)
    else:
        # Session expired — send anyway and let Wati decide
        await whatsapp.send_text(phone, msg)
        logger.warning(f"Payment confirmation sent outside session window for {phone} — may need template")

    logger.info(f"Payment confirmation sent to {phone}")


async def create_subscription(name: str, phone: str, coach_id: str, runner_id: str) -> str:
    """
    Create a Razorpay subscription via API and return the short_url payment link.
    The customer's phone and name are stored in notes so the webhook can identify them.
    Returns empty string if RAZORPAY_PLAN_ID is not configured or the call fails.
    """
    if not RAZORPAY_PLAN_ID or not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        logger.warning("Razorpay not fully configured — skipping subscription creation")
        return ""

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.razorpay.com/v1/subscriptions",
                auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
                json={
                    "plan_id":        RAZORPAY_PLAN_ID,
                    "total_count":    120,   # 10 years — effectively perpetual until cancelled
                    "customer_notify": 0,   # we notify via WhatsApp
                    "callback_url":   f"{APP_URL}/payment-success",
                    "notes": {
                        "name":            name,
                        "whatsapp_number": phone,
                        "coach_id":        coach_id,
                        "runner_id":       runner_id,
                    },
                },
                timeout=15,
            )
            resp.raise_for_status()
            short_url = resp.json().get("short_url", "")
            logger.info(f"Created Razorpay subscription for {phone}: {short_url}")
            return short_url
    except Exception as e:
        logger.error(f"Failed to create Razorpay subscription for {phone}: {e}")
        return ""


def verify_signature(payload_body: bytes, signature: str) -> bool:
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode() if RAZORPAY_WEBHOOK_SECRET else b"",
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
