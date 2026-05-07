from integrations.firebase_db import sheets
from integrations.whatsapp import whatsapp

ESCALATE_INTENTS = {"injury_flag", "dropout_risk"}


def should_escalate(intent: str, message: str, runner: dict) -> bool:
    return intent in ESCALATE_INTENTS


async def notify_coach(coach_id: str, runner: dict, message: str, reason: str):
    coach = sheets.get_coach_config(coach_id)
    runner_name = runner.get("name")

    escalation_msg = (
        f"⚠️ ESCALATION — {runner_name}\n\n"
        f"Situation: {reason}\n"
        f'Their message: "{message}"\n\n'
        f"Action needed: Reply with your instruction or:\n"
        f"(1) Rest day  (2) Modify plan  (3) Refer to physio"
    )

    await whatsapp.send_text(coach["coach_phone"], escalation_msg)
    sheets.log_platform_event("escalation", runner["runner_id"], coach_id, f"{reason}: {message}")
