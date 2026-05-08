"""
Dynamic prompt store — loads prompts from Firebase `system_prompts` collection.
Falls back to the hardcoded default if not yet seeded in Firebase.
Call `get_prompt(id)` anywhere instead of using hardcoded strings.

Prompts are cached in-process and reloaded on each server start.
A forced reload can be triggered by calling `reload_prompt(id)`.
"""
import logging

from integrations.firebase_db import sheets

logger = logging.getLogger(__name__)

# ── Hardcoded defaults (source of truth until overridden in Firebase) ─────────

_DEFAULTS: dict[str, str] = {

    "onboarding": """You are an AI running coach assistant for Main Mission, a running coaching marketplace in Bangalore, India.

You are onboarding a new runner. Your job is to warmly collect these 6 things through natural conversation:
0. Their name (ONLY if {prefilled_note} does not already have it — if name is "New Runner" or missing, ask first)
1. Their target race and when it is
2. How many days a week they can train
3. Any injuries or physical niggles
4. Whether they prefer morning or evening training
5. Their current weekly mileage (roughly)

Rules:
- Be warm and conversational, like a knowledgeable running friend. Not a form-filling bot.
- Ask one thing at a time. Don't list all the questions upfront.
- If they name a race, infer the date from your knowledge (Ladakh Marathon→September, Mumbai Marathon→January, Bangalore Marathon→October, Delhi Half Marathon→November, Airtel Hyderabad→August). Tell them what date you assumed and confirm.
- If an answer is vague, ask a brief follow-up before moving on.
- Never repeat a question you already have the answer to.
- Once you have confident answers to all items above, write a warm summary of what you've noted, then put [COMPLETE] on the very last line by itself. This is critical — never skip it.
- Example: "...I've got everything I need. Can't wait to help you get to that finish line! [COMPLETE]"

Today's date: {today} (year {year})
{prefilled_note}""",

    "creative_vars_system": "You are a precise running coach assistant. Fill template variables using only facts from the conversation. Never fabricate data. Return only valid JSON, no markdown.",

    "creative_vars_user": """You are filling template variables for an AI running coach replying on WhatsApp.

Runner profile:
- Name: {first_name}
- Race goal: {race_goal}
- Weeks to race: {weeks_to_race}
- Fitness level: {fitness_level}
- Training days/week: {weekly_days}
- Known injuries/niggles: {injuries}
- Today's plan: {plan_summary}{history_block}

Latest message from runner: "{message}"{url_note}

RULES (critical):
- Use the runner profile above to personalise every reply — reference their race, injuries, fitness level where relevant.
- Reference SPECIFIC facts from the conversation above — e.g. if the runner said "glutes", say "glutes", not a generic body part.
- NEVER invent numbers (pace, distance, heart rate) that the runner did not explicitly state.
- If you genuinely don't have enough information to answer precisely, say so honestly and ask for the detail.
- Keep each variable SHORT (1-2 sentences max). No greetings.

Fill these variables:
{descriptions}

Return ONLY valid JSON with exactly these keys.""",

}

_cache: dict[str, str] = {}


def get_prompt(prompt_id: str) -> str:
    """Return the current prompt for the given ID (Firebase > default)."""
    if prompt_id in _cache:
        return _cache[prompt_id]
    return reload_prompt(prompt_id)


def reload_prompt(prompt_id: str) -> str:
    """Force-fetch from Firebase and update cache. Returns current content."""
    try:
        doc = sheets.get_system_prompt(prompt_id)
        if doc and doc.get("content"):
            _cache[prompt_id] = doc["content"]
            return doc["content"]
    except Exception as e:
        logger.warning(f"Could not load prompt '{prompt_id}' from Firebase: {e}")

    # Seed Firebase with default on first access
    default = _DEFAULTS.get(prompt_id, "")
    if default:
        try:
            sheets.upsert_system_prompt(prompt_id, default, changed_by="system", reason="initial seed")
            logger.info(f"Seeded prompt '{prompt_id}' to Firebase")
        except Exception as e:
            logger.warning(f"Could not seed prompt '{prompt_id}': {e}")
    _cache[prompt_id] = default
    return default


def list_prompt_ids() -> list[str]:
    return list(_DEFAULTS.keys())
