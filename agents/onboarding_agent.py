import json
import logging
from datetime import date

from integrations.sheets import sheets
from integrations.llm import llm

logger = logging.getLogger(__name__)

QUESTIONS = [
    "What race are you training for, and when is it?",
    "How many days a week can you train?",
    "Any injuries or niggles I should know about?",
    "Are you more of a morning or evening runner?",
    "What's your current weekly mileage roughly?",
]

# In-memory store: {phone: {step, answers, coach_id, name, runner_id}}
# runner_id is set when updating an existing unboarded runner, None when creating fresh
_sessions: dict[str, dict] = {}


def start_onboarding(phone: str, coach_id: str, name: str = "New Runner", runner_id: str = None):
    _sessions[phone] = {
        "step": 0,
        "answers": [],
        "coach_id": coach_id,
        "name": name,
        "runner_id": runner_id,
    }
    logger.info(f"Onboarding started for {phone} (coach={coach_id})")


def is_onboarding(phone: str) -> bool:
    return phone in _sessions


async def handle_onboarding(phone: str, message: str) -> str:
    session = _sessions[phone]
    step = session["step"]

    if step > 0:
        session["answers"].append(message)

    if step < len(QUESTIONS):
        question = QUESTIONS[step]
        session["step"] += 1
        if step == 0:
            return (
                f"Welcome to Main Mission! I'm your AI coaching assistant. "
                f"I'll ask you 5 quick questions to set up your profile.\n\n{question}"
            )
        return question

    return await _complete_onboarding(phone, session)


async def _complete_onboarding(phone: str, session: dict) -> str:
    answers = session["answers"]
    coach_id = session["coach_id"]
    name = session["name"]

    parsed = await _extract_profile(answers)

    runner_data = {
        "name": name,
        "phone": phone,
        "coach_id": coach_id,
        "race_goal": parsed.get("race_goal", ""),
        "race_date": parsed.get("race_date", ""),
        "weekly_days": parsed.get("weekly_days", ""),
        "injuries": parsed.get("injuries", "None"),
        "fitness_level": parsed.get("fitness_level", "Intermediate"),
        "start_date": date.today().isoformat(),
        "status": "Active",
        "payment_status": "Trial",
        "onboarded": True,
    }

    existing_runner_id = session.get("runner_id")
    if existing_runner_id:
        sheets.update_runner(existing_runner_id, {
            "race_goal": runner_data["race_goal"],
            "race_date": runner_data["race_date"],
            "weekly_days": runner_data["weekly_days"],
            "injuries": runner_data["injuries"],
            "fitness_level": runner_data["fitness_level"],
            "onboarded": "TRUE",
        })
        runner_id = existing_runner_id
        logger.info(f"Updated existing runner {runner_id} after onboarding")
    else:
        runner_id = sheets.create_runner(runner_data)
        logger.info(f"Created new runner {runner_id} after onboarding")

    sheets.log_platform_event("onboarding", runner_id, coach_id, f"Onboarding completed for {name}")
    del _sessions[phone]

    coach = sheets.get_coach_config(coach_id)
    coach_name = coach.get("coach_name", "your coach") if coach else "your coach"

    return (
        f"You're all set, {name.split()[0]}! Here's what I've got:\n\n"
        f"Race: {parsed.get('race_goal', '—')}\n"
        f"Race date: {parsed.get('race_date') or '—'}\n"
        f"Training days: {parsed.get('weekly_days', '—')}/week\n"
        f"Injuries: {parsed.get('injuries', 'None')}\n"
        f"Fitness: {parsed.get('fitness_level', '—')}\n\n"
        f"{coach_name} will set up your training plan and you'll start receiving daily sessions soon. 🏃"
    )


async def _extract_profile(answers: list) -> dict:
    prompt = f"""Extract structured data from these onboarding answers. Return JSON only, no markdown.

Q1 (race goal and date): {answers[0]}
Q2 (training days per week): {answers[1]}
Q3 (injuries): {answers[2]}
Q4 (morning/evening preference): {answers[3]}
Q5 (current weekly mileage): {answers[4]}

Return exactly this JSON:
{{
  "race_goal": "e.g. Half Marathon",
  "race_date": "YYYY-MM-DD or empty string if unclear",
  "weekly_days": 4,
  "injuries": "e.g. Left knee ITB or None",
  "fitness_level": "Beginner or Intermediate or Advanced based on mileage"
}}"""

    try:
        raw = await llm.complete([
            {"role": "system", "content": "Extract structured data and return only valid JSON."},
            {"role": "user", "content": prompt},
        ])
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Profile extraction failed: {e}. Falling back to raw answers.")
        return {
            "race_goal": answers[0],
            "race_date": "",
            "weekly_days": "",
            "injuries": answers[2],
            "fitness_level": "Intermediate",
        }
