"""
Manually trigger onboarding for a runner whose payment was already captured
but the webhook didn't fire (e.g. webhook wasn't set up yet).

Usage:
    python -m scripts.manual_onboard \
        --name "Priya Sharma" \
        --phone "919876543210" \
        --coach "COACH_A" \
        --fee 2500

The script will:
  1. Check if runner already exists in Firebase (skip if so)
  2. Create runner with onboarded=FALSE
  3. Send the WhatsApp welcome template
  4. Log the event
"""

import sys, os, asyncio, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from datetime import date
from integrations.firebase_db import sheets
from integrations.whatsapp import whatsapp
from utils.helpers import normalize_phone


async def onboard(name: str, phone: str, coach_id: str, fee: float):
    phone_normalized = normalize_phone(phone)
    print(f"\nOnboarding: {name} | {phone_normalized} | coach={coach_id} | ₹{fee}")

    # Check if already exists
    existing = sheets.find_any_runner_by_phone(phone_normalized)
    if existing:
        already_onboarded = str(existing.get("onboarded", "FALSE")).upper() == "TRUE"
        print(f"⚠  Runner already exists: {existing['runner_id']} — onboarded={existing.get('onboarded')}")
        if already_onboarded:
            print("   Nothing to do — runner is fully onboarded.")
            return
        print("   Runner exists but not onboarded — sending welcome message again...")
        runner_id = existing["runner_id"]
    else:
        # Create runner
        runner_id = sheets.create_runner({
            "name":           name,
            "phone":          phone_normalized,
            "coach_id":       coach_id,
            "monthly_fee":    fee,
            "payment_status": "Paid",
            "start_date":     date.today().isoformat(),
            "status":         "Active",
            "onboarded":      False,
            "notes":          "Manually onboarded via script",
        })
        print(f"✓  Runner created: {runner_id}")

    # Get coach
    coach = sheets.get_coach_config(coach_id)
    if not coach:
        print(f"✗  Coach '{coach_id}' not found. Check coach_id.")
        return
    coach_name = coach.get("coach_name", "your coach")

    # Send WhatsApp welcome
    first_name = name.split()[0]
    print(f"   Sending WhatsApp welcome to {phone_normalized}...")
    await whatsapp.send_template(
        phone=phone_normalized,
        template_name="onboarding_welcome",
        variables={"runner_name": first_name, "coach_name": coach_name},
    )

    sheets.log_platform_event(
        "manual_onboard", runner_id, coach_id,
        f"Manually onboarded {name} via script — ₹{fee}"
    )
    print(f"✓  Welcome message sent to {phone_normalized}")
    print(f"   Runner will start onboarding when they reply to WhatsApp.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name",   required=True,  help="Runner's full name")
    parser.add_argument("--phone",  required=True,  help="Phone with country code e.g. 919876543210")
    parser.add_argument("--coach",  required=True,  help="Coach ID e.g. COACH_A")
    parser.add_argument("--fee",    type=float, default=0, help="Monthly fee in INR")
    args = parser.parse_args()

    asyncio.run(onboard(args.name, args.phone, args.coach, args.fee))
