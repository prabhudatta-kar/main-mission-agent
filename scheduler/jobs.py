from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config.settings import MORNING_MESSAGE_HOUR, EVENING_CHECKIN_HOUR, DIGEST_HOUR
from integrations.sheets import sheets
from integrations.whatsapp import whatsapp

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


def start_scheduler():
    scheduler.add_job(send_morning_messages, "cron", hour=MORNING_MESSAGE_HOUR, minute=0)
    scheduler.add_job(evening_checkin, "cron", hour=EVENING_CHECKIN_HOUR, minute=0)
    scheduler.add_job(send_coach_digest, "cron", hour=DIGEST_HOUR, minute=0)
    scheduler.start()


async def send_morning_messages():
    for runner in sheets.get_all_active_runners():
        plan = sheets.get_todays_plan(runner["runner_id"])
        if not plan:
            continue

        if plan["day_type"] == "Rest":
            await whatsapp.send_template(
                phone=runner["phone"],
                template_name="rest_day_message",
                variables={"runner_name": runner["name"].split()[0]}
            )
        else:
            await whatsapp.send_template(
                phone=runner["phone"],
                template_name="daily_workout_prompt",
                variables={
                    "runner_name": runner["name"].split()[0],
                    "session_type": plan["session_type"]
                }
            )

        sheets.mark_plan_sent(plan["plan_id"])


async def evening_checkin():
    for runner in sheets.get_runners_with_no_feedback_today():
        await whatsapp.send_template(
            phone=runner["phone"],
            template_name="missed_session_checkin",
            variables={"runner_name": runner["name"].split()[0]}
        )


async def send_coach_digest():
    for coach in sheets.get_all_active_coaches():
        summary = sheets.get_todays_summary(coach["coach_id"])
        completed = summary["completed"]
        total = summary["total"]
        flagged_count = len(summary["flagged"])

        flag_text = f" {flagged_count} flagged." if flagged_count else ""
        digest = f"Today: {completed}/{total} completed.{flag_text} Reply SUMMARY for details."
        await whatsapp.send_text(coach["coach_phone"], digest)
