"""
One-time migration: give all onboarded-but-unpaid runners a 2-week free trial.

What it does:
  1. Finds all runners with payment_status="Unpaid" and onboarded="TRUE"
  2. Sets payment_status="Trial", trial_start_date=today, trial_end_date=today+TRIAL_DAYS
  3. Optionally sends them a WhatsApp message explaining the trial
  4. Does NOT cancel or touch existing Razorpay subscription links

Run with:
  python -m scripts.migrate_to_trial [--send-message]
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from datetime import date, timedelta
from integrations.firebase_db import sheets
from config.settings import TRIAL_DAYS

SEND_MESSAGES = "--send-message" in sys.argv


async def _send(phone: str, msg: str):
    if not SEND_MESSAGES:
        return
    from integrations.whatsapp import whatsapp
    await whatsapp.send_text(phone, msg)


async def main():
    today     = date.today()
    trial_end = today + timedelta(days=TRIAL_DAYS)
    end_str   = trial_end.strftime("%-d %B")

    runners = sheets.get_all_active_runners()
    targets = [
        r for r in runners
        if r.get("payment_status") in ("Unpaid", "Pending", "")
        and str(r.get("onboarded", "FALSE")).upper() == "TRUE"
    ]

    if not targets:
        print("No unpaid onboarded runners found.")
        return

    print(f"Found {len(targets)} runners to migrate (trial ends {trial_end.isoformat()})")
    if SEND_MESSAGES:
        print("--send-message flag set: will send WhatsApp messages")
    else:
        print("Dry run for messages — pass --send-message to actually send")

    for r in targets:
        runner_id = r["runner_id"]
        name      = r.get("name", "Runner")
        first     = name.split()[0] if name not in ("New Runner", "", None) else ""
        phone     = r.get("phone", "")

        sheets.update_runner(runner_id, {
            "payment_status":   "Trial",
            "status":           "Active",
            "trial_start_date": today.isoformat(),
            "trial_end_date":   trial_end.isoformat(),
        })

        msg = (
            f"Good news{', ' + first if first else ''}! We're giving everyone a 2-week free trial — "
            f"no payment needed right now. You have full access until {end_str}. "
            f"We'll send a subscription link then to keep things going."
        )

        await _send(phone, msg)
        print(f"  ✓ {runner_id} ({name}) → Trial until {trial_end.isoformat()}"
              + (f" | message sent to {phone}" if SEND_MESSAGES else ""))

    print(f"\nDone. {len(targets)} runners migrated to Trial status.")


if __name__ == "__main__":
    asyncio.run(main())
