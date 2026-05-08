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


async def _send(runner: dict, message: str, template_name: str, variables: dict):
    """
    Send via free-form text if runner is in an active WhatsApp session (messaged within 24h),
    otherwise use a pre-approved template.
    """
    phone = runner["phone"]
    rid   = runner["runner_id"]

    if sheets.is_within_session_window(rid):
        await whatsapp.send_text(phone, message)
    else:
        await whatsapp.send_template(phone=phone, template_name=template_name, variables=variables)


async def send_morning_messages():
    for runner in sheets.get_all_active_runners():
        plan = sheets.get_todays_plan(runner["runner_id"])
        if not plan:
            continue

        rid      = runner["runner_id"]
        coach_id = runner["coach_id"]
        first    = runner["name"].split()[0]
        weeks    = _weeks_left(runner.get("race_date", ""))
        race     = runner.get("race_goal", "your race")

        if plan["day_type"] == "Rest":
            message   = f"Rest day today, {first}! You've put in the hard work — recovery is where the fitness actually builds. Reply READY if you're set for tomorrow 💪"
            template  = "mm_morning_rest_day"
            variables = {"first_name": first}
        else:
            session = plan.get("session_type", "Run")
            dist    = plan.get("distance_km", "")
            intens  = plan.get("intensity", "easy")
            message  = f"Morning {first}! Today: {session} — {dist}km at {intens} pace. {weeks}w to {race}. Reply GO for full details 🏃"
            template = "mm_morning_run"
            variables = {
                "first_name":   first,
                "session_type": session,
                "distance":     str(dist),
                "intensity":    intens,
                "weeks_to_race": str(weeks),
                "race_goal":    race,
            }

        await _send(runner, message, template, variables)
        sheets.mark_plan_sent(plan["plan_id"])
        sheets.log_conversation(rid, coach_id, inbound="", outbound=message, intent="workout")


async def evening_checkin():
    for runner in sheets.get_runners_with_no_feedback_today():
        rid      = runner["runner_id"]
        coach_id = runner["coach_id"]
        first    = runner["name"].split()[0]
        message  = f"Hey {first}, missed you on the roads today! Rest day or life happened? Just reply and let me know 🙂"

        await _send(runner, message, "mm_evening_checkin", {"first_name": first})
        sheets.log_conversation(rid, coach_id, inbound="", outbound=message, intent="checkin")


async def send_coach_digest():
    for coach in sheets.get_all_active_coaches():
        summary       = sheets.get_todays_summary(coach["coach_id"])
        completed     = summary["completed"]
        total         = summary["total"]
        flagged_count = len(summary["flagged"])
        flag_text     = f" {flagged_count} flagged." if flagged_count else ""
        digest        = f"Today: {completed}/{total} completed.{flag_text} Reply SUMMARY for details."
        await whatsapp.send_text(coach["coach_phone"], digest)


def _weeks_left(race_date_str: str) -> int:
    if not race_date_str:
        return 0
    try:
        from datetime import date
        return max(0, (date.fromisoformat(str(race_date_str)) - date.today()).days // 7)
    except Exception:
        return 0
