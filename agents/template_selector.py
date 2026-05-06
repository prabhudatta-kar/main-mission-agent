"""
Template selector: picks the right template by rule (no LLM), fills factual
variables from real runner data, and only calls the LLM for the small number
of variables that need a generated sentence (observation, answer, highlight).

This guarantees responses are always anchored to an approved template body.
"""
import json
import logging
import re

from integrations.llm import llm
from templates.catalog import TEMPLATES, fill_template
from utils.helpers import weeks_until

logger = logging.getLogger(__name__)

# ── Rule-based intent → template ─────────────────────────────────────────────

def _pick_template(intent: str, message: str, history: list) -> str:
    msg = message.lower()

    if intent == "injury_flag":
        return "injury_response"

    if intent == "dropout_risk":
        return "dropout_risk"

    if intent == "missed_session":
        # Count recent missed messages to decide severity
        recent_misses = sum(
            1 for m in history[-10:]
            if m.get("direction") == "inbound"
            and any(k in m.get("message", "").lower() for k in ["missed", "skip", "couldn't", "didn't run"])
        )
        return "missed_multiple" if recent_misses >= 2 else "missed_first_time"

    if intent == "feedback":
        if any(k in msg for k in ["pb", "personal best", "fastest", "best ever", "new record"]):
            return "feedback_great"
        if any(k in msg for k in ["tough", "hard", "difficult", "struggled", "tired", "heavy", "bad"]):
            return "feedback_tough"
        return "feedback_solid"

    # Default: question or anything else
    return "question_general"


# ── Variable extraction from real data ───────────────────────────────────────

_BODY_PARTS = [
    "knee", "ankle", "calf", "shin", "hip", "foot", "hamstring",
    "quad", "quadricep", "back", "shoulder", "it band", "achilles", "heel",
]

def _extract_body_part(message: str) -> str:
    msg = message.lower()
    for part in _BODY_PARTS:
        if part in msg:
            return part
    return "injury"


def _extract_distance(message: str, plan) -> str:
    match = re.search(r"(\d+\.?\d*)\s*km", message.lower())
    if match:
        return match.group(1)
    if plan and plan.get("distance_km"):
        return str(plan["distance_km"])
    return ""


def _data_vars(runner: dict, plan, message: str) -> dict:
    """Variables that come directly from data — no LLM needed."""
    name = runner.get("name") or "there"
    return {
        "first_name":    name.split()[0],
        "race_goal":     runner.get("race_goal") or "your goal race",
        "weeks_to_race": str(weeks_until(runner.get("race_date") or "")),
        "distance":      _extract_distance(message, plan),
        "session_type":  (plan.get("session_type") or "run").lower() if plan else "run",
        "intensity":     (plan.get("intensity") or "easy").lower() if plan else "easy",
        "body_part":     _extract_body_part(message),
    }


# ── LLM fills only the creative/open-ended variables ─────────────────────────

_CREATIVE_DESCRIPTIONS = {
    "observation":        "1 sentence specific observation about their run — no greeting",
    "highlight":          "1 sentence describing what was exceptional",
    "answer":             "1-2 sentence direct answer to the runner's question — no greeting",
    "coach_note":         "1 sentence coach feedback",
    "change_description": "brief description of the plan change",
    "reason":             "brief reason for the change",
    "extra_note":         "one short running tip relevant to the message, or empty string",
}

async def _fill_creative_vars(
    needed_vars: set, runner: dict, plan, message: str, base_vars: dict
) -> dict:
    """Ask LLM for only the variables that can't come from data."""
    if not needed_vars:
        return {}

    descriptions = {v: _CREATIVE_DESCRIPTIONS.get(v, "short relevant value") for v in needed_vars}
    prompt = f"""You are filling blanks in a WhatsApp message template for a running coach.

Runner: {base_vars['first_name']}, training for {base_vars['race_goal']}
Their message: "{message}"

Fill these variables — keep each value SHORT and specific (no greetings, no extra text):
{json.dumps(descriptions, indent=2)}

Return ONLY valid JSON with exactly these keys."""

    try:
        raw = await llm.complete([
            {"role": "system", "content": "Fill template variables. Return only valid JSON, no markdown."},
            {"role": "user", "content": prompt},
        ])
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Creative var generation failed: {e}")
        return {v: "" for v in needed_vars}


# ── Main entry point ──────────────────────────────────────────────────────────

async def select_template_response(
    runner: dict, plan, history: list, message: str, intent: str
) -> str:
    """
    Returns the exact filled template text — same content that would go to WhatsApp.
    Template is chosen by rule; variables filled from data first, LLM only for the rest.
    """
    template_id = _pick_template(intent, message, history)
    tmpl = TEMPLATES.get(template_id)
    if not tmpl:
        logger.warning(f"No template found for id={template_id}")
        return f"{(runner.get('name') or 'there').split()[0]}, I'll pass this to your coach 🙏"

    base = _data_vars(runner, plan, message)

    # Find which variables still need LLM to fill
    required = set(tmpl["variables"])
    already_filled = required & set(base.keys())
    needs_llm = required - already_filled

    creative = await _fill_creative_vars(needs_llm, runner, plan, message, base)
    all_vars = {**base, **creative}

    try:
        result = fill_template(template_id, all_vars)
        logger.info(f"Template selected: {template_id} | intent: {intent}")
        return result
    except KeyError as e:
        logger.error(f"Missing variable {e} for template {template_id}, vars={list(all_vars.keys())}")
        return f"{base['first_name']}, I'll pass this to your coach 🙏"
