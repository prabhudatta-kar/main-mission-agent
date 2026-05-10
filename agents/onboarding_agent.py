import json
import logging
from datetime import date

from agents.prompt_store import get_prompt
from integrations.firebase_db import sheets
from integrations.llm import llm
from integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)

# Sessions are stored in Firestore `onboarding_sessions` collection —
# survives restarts and works across multiple instances.


def is_onboarding(phone: str) -> bool:
    return sheets.get_onboarding_session(phone) is not None


def start_onboarding(phone: str, coach_id: str, name: str = "New Runner",
                     runner_id: str = None, prefilled: dict = None):
    prefilled = prefilled or {}
    notes = []

    if not name or name in ("New Runner", ""):
        notes.append("Runner's name is NOT known — ask for their name as the very first question.")

    if prefilled:
        known = ", ".join(f"{k}={v}" for k, v in prefilled.items() if v)
        notes.append(f"Already known from their signup: {known}. Don't ask for these again.")

    prefilled_note = " ".join(notes)

    system_prompt = get_prompt("onboarding").format(
        today=date.today().isoformat(),
        year=date.today().year,
        prefilled_note=prefilled_note,
    )

    sheets.save_onboarding_session(phone, {
        "phone":     phone,
        "history":   [],
        "coach_id":  coach_id,
        "name":      name,
        "runner_id": runner_id,
        "prefilled": prefilled,
        "system":    system_prompt,
    })
    logger.info(f"Onboarding started for {phone} (coach={coach_id})")


async def handle_onboarding(phone: str, message: str) -> str:
    session = sheets.get_onboarding_session(phone)
    if not session:
        logger.error(f"No onboarding session found for {phone}")
        return "Something went wrong — please message us again to restart."

    history = session.get("history", [])
    history.append({"role": "user", "content": message})

    messages = [{"role": "system", "content": session["system"]}] + history
    raw_response = await llm.complete(messages)
    clean_response = raw_response.replace("[COMPLETE]", "").strip()

    if not clean_response:
        sname = session.get("name", "")
        first = sname.split()[0] if sname not in ("New Runner", "", None) else ""
        clean_response = f"Got everything I need{', ' + first if first else ''}. Let me get your plan set up."

    history.append({"role": "assistant", "content": clean_response})
    lm_complete = "[COMPLETE]" in raw_response

    if lm_complete:
        # Persist final history before completing (in case _complete_onboarding errors)
        session["history"] = history
        try:
            await _complete_onboarding(phone, session)
        except Exception as e:
            logger.error(f"Failed to save onboarding for {phone}: {e}")
        return ""

    # Save updated history back to Firestore
    session["history"] = history
    sheets.save_onboarding_session(phone, session)
    return clean_response


async def _complete_onboarding(phone: str, session: dict) -> None:
    parsed = await _extract_profile(session["history"], session.get("prefilled", {}))

    existing_runner_id = session.get("runner_id")
    if existing_runner_id:
        update_fields = {
            "races":            parsed.get("races", []),
            "race_goal":        parsed.get("race_goal", ""),
            "race_date":        parsed.get("race_date", ""),
            "race_distance":    parsed.get("race_distance", ""),
            "weekly_days":      parsed.get("weekly_days", ""),
            "injuries":         parsed.get("injuries", "None"),
            "fitness_level":    parsed.get("fitness_level", "Intermediate"),
            "additional_notes": parsed.get("additional_notes", ""),
            "onboarded":        "TRUE",
        }
        if parsed.get("name") and session.get("name") in ("New Runner", "", None):
            update_fields["name"] = parsed["name"]
        sheets.update_runner(existing_runner_id, update_fields)
        runner_id = existing_runner_id
    else:
        runner_id = sheets.create_runner({
            "name":             session.get("name", ""),
            "phone":            phone,
            "coach_id":         session.get("coach_id", ""),
            "races":            parsed.get("races", []),
            "race_goal":        parsed.get("race_goal", ""),
            "race_date":        parsed.get("race_date", ""),
            "race_distance":    parsed.get("race_distance", ""),
            "weekly_days":      parsed.get("weekly_days", ""),
            "injuries":         parsed.get("injuries", "None"),
            "fitness_level":    parsed.get("fitness_level", "Intermediate"),
            "additional_notes": parsed.get("additional_notes", ""),
            "start_date":       date.today().isoformat(),
            "status":           "Active",
            "payment_status":   "Trial",
            "onboarded":        True,
        })

    sheets.log_platform_event("onboarding", runner_id, session.get("coach_id", ""),
                              f"Onboarding completed for {session.get('name')}")
    sheets.delete_onboarding_session(phone)
    logger.info(f"Onboarding completed for {phone} → runner {runner_id}")

    await _send_payment_link(phone, runner_id, session)


async def _resolve_race(race_name: str) -> dict:
    """Look up race in Firebase, fall back to web search. Returns {name, date} or {}."""
    if not race_name:
        return {}
    try:
        from integrations.race_lookup import lookup_race
        race = await lookup_race(race_name)
        if race:
            return {"name": race.get("name", race_name), "date": race.get("date", "")}
    except Exception as e:
        logger.warning(f"Race lookup failed for '{race_name}': {e}")
    return {}


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
  "name": "runner's first and last name if mentioned, else empty string",
  "races": [
    {{
      "name": "race name",
      "date": "YYYY-MM-DD or empty string if unknown",
      "distance": "42.2km / 21.1km / 10km etc, empty if not mentioned"
    }}
  ],
  "weekly_days": 4,
  "injuries": "description or None",
  "fitness_level": "Beginner (under 20km/wk) or Intermediate (20-50km/wk) or Advanced (50km+/wk)",
  "additional_notes": "anything else the runner shared — running history, goals, lifestyle, motivation etc. Empty string if nothing"
}}"""

    try:
        raw = await llm.complete([
            {"role": "system", "content": "Extract structured runner data from a conversation. Return only valid JSON."},
            {"role": "user",   "content": prompt},
        ])
        raw    = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)

        # Resolve each race against the calendar
        races = parsed.get("races") or []
        if not races and parsed.get("race_goal"):
            # backwards compat if LLM returned old format
            races = [{"name": parsed["race_goal"], "date": parsed.get("race_date", ""), "distance": parsed.get("race_distance", "")}]

        resolved_races = []
        for r in races:
            result = await _resolve_race(r.get("name", ""))
            if result:
                resolved_races.append({
                    "name":     result.get("name", r["name"]),
                    "date":     r.get("date") or result.get("date", ""),
                    "distance": r.get("distance", ""),
                })
            else:
                resolved_races.append(r)

        parsed["races"] = resolved_races
        # Primary race = first upcoming one
        from datetime import date as _dt
        today = _dt.today().isoformat()
        upcoming = sorted([r for r in resolved_races if r.get("date", "") >= today], key=lambda r: r["date"])
        primary = upcoming[0] if upcoming else (resolved_races[0] if resolved_races else {})
        parsed["race_goal"]     = primary.get("name", "")
        parsed["race_date"]     = primary.get("date", "")
        parsed["race_distance"] = primary.get("distance", "")

        return parsed
    except Exception as e:
        logger.warning(f"Profile extraction failed: {e}")
        return {"name": "", "race_goal": "", "race_date": "", "weekly_days": "", "injuries": "None", "fitness_level": "Intermediate"}


async def _send_payment_link(phone: str, runner_id: str, session: dict):
    try:
        from integrations.razorpay import create_subscription
        name     = session.get("name", "Runner")
        coach_id = session.get("coach_id", "")
        first    = name.split()[0] if name not in ("New Runner", "", None) else ""

        short_url = await create_subscription(
            name=name, phone=phone, coach_id=coach_id, runner_id=runner_id
        )

        if short_url:
            sheets.update_runner(runner_id, {"payment_link": short_url})
            msg = (
                f"Got everything I need{', ' + first if first else ''}. "
                f"Last step — set up your subscription here:\n{short_url}"
            )
        else:
            msg = (
                f"Got everything I need{', ' + first if first else ''}. "
                f"Your coach will be in touch within 24 hours to get things started."
            )

        await whatsapp.send_text(phone, msg)
        logger.info(f"Payment link sent to {phone}: {short_url or '(Razorpay not configured)'}")

    except Exception as e:
        logger.error(f"Failed to send payment link to {phone}: {e}")
