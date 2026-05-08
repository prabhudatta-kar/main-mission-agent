from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config.settings import MORNING_MESSAGE_HOUR, EVENING_CHECKIN_HOUR, DIGEST_HOUR
from integrations.firebase_db import sheets
from integrations.whatsapp import whatsapp

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


def start_scheduler():
    scheduler.add_job(send_morning_messages, "cron", hour=MORNING_MESSAGE_HOUR, minute=0)
    scheduler.add_job(evening_checkin,        "cron", hour=EVENING_CHECKIN_HOUR, minute=0)
    scheduler.add_job(send_coach_digest,      "cron", hour=DIGEST_HOUR,          minute=0)
    scheduler.start()


async def send_morning_messages():
    for runner in sheets.get_all_active_runners():
        plan = sheets.get_todays_plan(runner["runner_id"])
        if not plan:
            continue

        rid      = runner["runner_id"]
        coach_id = runner["coach_id"]
        first    = runner["name"].split()[0]

        if plan["day_type"] == "Rest":
            template = "mm_morning_rest_day"
            msg_text = f"Rest day today, {first}! Recovery is where the gains happen 💪"
            variables = {"first_name": first}
        else:
            template = "mm_morning_run"
            msg_text = (f"Morning {first}! Today: {plan.get('session_type','')} — "
                       f"{plan.get('distance_km','')}km at {plan.get('intensity','')} pace 🏃")
            variables = {
                "first_name":    first,
                "session_type":  plan.get("session_type", ""),
                "distance":      str(plan.get("distance_km", "")),
                "intensity":     plan.get("intensity", ""),
                "weeks_to_race": str(_weeks_left(runner.get("race_date", ""))),
                "race_goal":     runner.get("race_goal", "your race"),
            }

        await whatsapp.send_template(phone=runner["phone"], template_name=template, variables=variables)
        sheets.mark_plan_sent(plan["plan_id"])

        # Log to Firebase so it appears in dashboard history
        sheets.log_conversation(rid, coach_id, inbound="", outbound=msg_text, intent="workout")


async def evening_checkin():
    for runner in sheets.get_runners_with_no_feedback_today():
        rid      = runner["runner_id"]
        coach_id = runner["coach_id"]
        first    = runner["name"].split()[0]
        msg_text = f"Hey {first}, missed you on the roads today! Rest day or life happened? Just reply 🙂"

        await whatsapp.send_template(
            phone=runner["phone"],
            template_name="mm_evening_checkin",
            variables={"first_name": first}
        )
        sheets.log_conversation(rid, coach_id, inbound="", outbound=msg_text, intent="checkin")


async def send_coach_digest():
    for coach in sheets.get_all_active_coaches():
        summary      = sheets.get_todays_summary(coach["coach_id"])
        completed    = summary["completed"]
        total        = summary["total"]
        flagged_count = len(summary["flagged"])

        flag_text = f" {flagged_count} flagged." if flagged_count else ""
        digest    = f"Today: {completed}/{total} completed.{flag_text} Reply SUMMARY for details."
        await whatsapp.send_text(coach["coach_phone"], digest)


def _weeks_left(race_date_str: str) -> int:
    if not race_date_str:
        return 0
    try:
        from datetime import date
        return max(0, (date.fromisoformat(str(race_date_str)) - date.today()).days // 7)
    except Exception:
        return 0
