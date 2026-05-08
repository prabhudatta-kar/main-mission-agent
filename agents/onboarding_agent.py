import json
import logging
from datetime import date

from agents.prompt_store import get_prompt
from integrations.firebase_db import sheets
from integrations.llm import llm

logger = logging.getLogger(__name__)

# {phone: {history, coach_id, name, runner_id, prefilled}}
_sessions: dict = {}


def is_onboarding(phone: str) -> bool:
    return phone in _sessions


def start_onboarding(phone: str, coach_id: str, name: str = "New Runner",
                     runner_id: str = None, prefilled: dict = None):
    prefilled = prefilled or {}
    prefilled_note = ""
    if prefilled:
        known = ", ".join(f"{k}={v}" for k, v in prefilled.items() if v)
        prefilled_note = f"Already known from their signup: {known}. Don't ask for these again."

    system_prompt = get_prompt("onboarding").format(
        today=date.today().isoformat(),
        year=date.today().year,
        prefilled_note=prefilled_note,
    )
    _sessions[phone] = {
        "history": [],
        "coach_id": coach_id,
        "name": name,
        "runner_id": runner_id,
        "prefilled": prefilled,
        "system": system_prompt,
    }
    logger.info(f"Onboarding started for {phone} (coach={coach_id})")


async def handle_onboarding(phone: str, message: str) -> str:
    session = _sessions[phone]
    session["history"].append({"role": "user", "content": message})

    messages = [{"role": "system", "content": session["system"]}] + session["history"]
    raw_response = await llm.complete(messages)
    clean_response = raw_response.replace("[COMPLETE]", "").strip()
    if not clean_response:
        clean_response = f"Great, I think I have everything I need, {session['name'].split()[0]}! Let me get your plan set up 🏃"
    session["history"].append({"role": "assistant", "content": clean_response})

    # Trigger completion if LLM signalled it OR if we can extract all 5 fields
    user_turns = sum(1 for m in session["history"] if m["role"] == "user")
    lm_complete = "[COMPLETE]" in raw_response
    profile_complete = lm_complete or (user_turns >= 5 and await _is_profile_complete(session))

    if profile_complete:
        try:
            await _complete_onboarding(phone, session)
        except Exception as e:
            logger.error(f"Failed to save onboarding for {phone}: {e}")

    return clean_response


async def _complete_onboarding(phone: str, session: dict) -> None:
    parsed = await _extract_profile(session["history"], session["prefilled"])

    runner_data = {
        "name": session["name"],
        "phone": phone,
        "coach_id": session["coach_id"],
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
    else:
        runner_id = sheets.create_runner(runner_data)

    sheets.log_platform_event("onboarding", runner_id, session["coach_id"],
                              f"Onboarding completed for {session['name']}")
    del _sessions[phone]
    logger.info(f"Onboarding completed and saved for {phone} → runner {runner_id}")


async def _is_profile_complete(session: dict) -> bool:
    """Return True if all 5 onboarding fields can be extracted from the conversation."""
    parsed = await _extract_profile(session["history"], session["prefilled"])
    return bool(
        parsed.get("race_goal") and
        parsed.get("weekly_days") and
        parsed.get("injuries") is not None and
        parsed.get("fitness_level")
    )


async def _extract_profile(history: list, prefilled: dict) -> dict:
    today = date.today()
    history_text = "\n".join(
        f"{'Runner' if m['role'] == 'user' else 'Agent'}: {m['content']}"
        for m in history
    )

    prompt = f"""Extract the runner's profile from this onboarding conversation. Today is {today.isoformat()} (year {today.year}).

{history_text}

Also consider these already-known values: {json.dumps(prefilled)}

Return this exact JSON, no markdown:
{{
  "race_goal": "short race name",
  "race_date": "YYYY-MM-DD — use the date mentioned or inferred in conversation; if only month known use the 15th; empty string if unknown",
  "weekly_days": 4,
  "injuries": "description or None",
  "fitness_level": "Beginner (under 20km/wk) or Intermediate (20-50km/wk) or Advanced (50km+/wk)"
}}"""

    try:
        raw = await llm.complete([
            {"role": "system", "content": "Extract structured runner data from a conversation. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ])
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Profile extraction failed: {e}")
        return {"race_goal": "", "race_date": "", "weekly_days": "", "injuries": "None", "fitness_level": "Intermediate"}
