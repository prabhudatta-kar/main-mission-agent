"""
Template selector: picks the right template by rule (no LLM), fills factual
variables from real runner data, and only calls the LLM for the small number
of variables that need a generated sentence (observation, answer, highlight).

This guarantees responses are always anchored to an approved template body.
"""
import json
import logging
import re
from datetime import date, timedelta

from agents.coaching_kb import get_coaching_context
from agents.prompt_store import get_prompt
from integrations.firebase_db import sheets
from integrations.llm import llm
from integrations.strava import STRAVA_ACTIVITY_RE, fetch_strava_context
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
    race_goal = runner.get("race_goal") or "your goal race"
    race_dist = runner.get("race_distance") or ""
    race_label = f"{race_goal} {race_dist}".strip() if race_dist else race_goal
    return {
        "first_name":    name.split()[0],
        "race_goal":     race_label,
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
    needed_vars: set, runner: dict, plan, message: str, base_vars: dict,
    history: list = None, intent: str = "question"
) -> dict:  # noqa: C901
    """Ask LLM for only the variables that can't come from data."""
    if not needed_vars:
        return {}

    # Build context block: memory summary (long-term) + recent thread (short-term)
    history_block = ""

    memory = runner.get("_memory", {})
    if memory:
        mem_parts = []
        if memory.get("summary"):        mem_parts.append(f"Background: {memory['summary']}")
        if memory.get("known_issues"):   mem_parts.append(f"Known issues: {memory['known_issues']}")
        if memory.get("coaching_notes"): mem_parts.append(f"Coaching style: {memory['coaching_notes']}")
        if memory.get("recent_form"):    mem_parts.append(f"Recent form: {memory['recent_form']}")
        if memory.get("watch_points"):   mem_parts.append(f"Watch: {memory['watch_points']}")
        if mem_parts:
            history_block = "\n\nRunner memory (AI-generated daily summary):\n" + "\n".join(mem_parts)

    if history:
        lines = []
        for m in history[-5:]:
            direction = m.get("direction", "")
            text = (m.get("message") or "").strip()
            if not text:
                continue
            if direction == "inbound":
                lines.append(f"Runner: {text}")
            elif direction == "outbound":
                lines.append(f"Coach AI: {text}")
        if lines:
            history_block += "\n\nCurrent conversation:\n" + "\n".join(lines)

    # Fetch context for Strava links; warn about other URLs we can't access
    url_note = ""
    strava_match = STRAVA_ACTIVITY_RE.search(message)
    if strava_match:
        url_note = "\n" + await fetch_strava_context(strava_match.group(0)) + "\n"
    elif re.search(r"https?://", message):
        url_note = "\nNOTE: The runner shared a URL you cannot access. Do not invent data from it — ask them to paste the key numbers directly.\n"

    descriptions = {v: _CREATIVE_DESCRIPTIONS.get(v, "short relevant value") for v in needed_vars}

    # Build plan summary — rich enough that LLM follow-ups don't hallucinate
    if plan and str(plan.get("day_type", "")).lower() != "rest":
        reps     = plan.get("reps", "")
        rep_dist = plan.get("rep_distance_m", "")
        dist     = plan.get("distance_km", "")
        duration = plan.get("duration_min", "")
        if reps and rep_dist:
            metric = f"{reps} × {rep_dist}m"
        elif dist and str(dist) not in ("0", ""):
            metric = f"{dist}km"
        elif duration and str(duration) not in ("0", ""):
            metric = f"{duration}min"
        else:
            metric = ""
        plan_parts = [
            f"Session type: {plan.get('session_type','Run')}",
            f"Distance/Volume: {metric or 'not specified'}",
            f"Intensity: {plan.get('intensity','easy')}",
            f"RPE target: {plan.get('rpe_target','') or 'not specified'}",
        ]
        if plan.get("coach_notes"):
            plan_parts.append(f"Coach notes: {plan['coach_notes']}")
        if plan.get("workout_notes"):
            plan_parts.append(f"Workout notes: {plan['workout_notes']}")
        plan_summary = "\n".join(plan_parts)
    else:
        # No plan today — look for next upcoming session so LLM doesn't invent one
        runner_id = runner.get("runner_id", "")
        upcoming = []
        if runner_id:
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            week_end  = (date.today() + timedelta(days=14)).isoformat()
            upcoming  = sheets.get_runner_plans(runner_id, from_date=tomorrow, to_date=week_end)
            upcoming  = [p for p in upcoming if str(p.get("day_type", "")).lower() != "rest"]
        if upcoming:
            nxt = upcoming[0]
            plan_summary = (
                f"Today is a rest day. Next session: {nxt.get('date','')} — "
                f"{nxt.get('session_type','Run')} {nxt.get('distance_km','')}km "
                f"at {nxt.get('intensity','easy')}"
            )
        else:
            plan_summary = "Rest day today / no upcoming sessions found in the next 2 weeks."

    user_prompt = (
        get_prompt("creative_vars_user")
        .replace("{first_name}",    base_vars["first_name"])
        .replace("{race_goal}",     base_vars["race_goal"])
        .replace("{weeks_to_race}", base_vars.get("weeks_to_race", "unknown"))
        .replace("{fitness_level}", runner.get("fitness_level") or "unknown")
        .replace("{weekly_days}",   str(runner.get("weekly_days") or "unknown"))
        .replace("{injuries}",      runner.get("injuries") or "none reported")
        .replace("{plan_summary}",  plan_summary)
        .replace("{history_block}", history_block)
        .replace("{message}",       message)
        .replace("{url_note}",      url_note)
        .replace("{descriptions}",  json.dumps(descriptions, indent=2))
    )

    # Build system message: base tone rules → KB context → coach rules (highest priority)
    coaching_ctx = get_coaching_context(intent, message)
    system_msg   = get_prompt("creative_vars_system") + "\nReturn only valid JSON. No markdown."

    if coaching_ctx:
        system_msg = f"{system_msg}\n\n{coaching_ctx}"

    # Coach's personal rules override the knowledge base
    coach_id = runner.get("coach_id", "")
    if coach_id:
        coach_rules = sheets.get_active_rules(coach_id)
        if coach_rules:
            rules_text = "\n".join(
                f"- {r['rule_derived']}" for r in coach_rules if r.get("rule_derived")
            )
            system_msg += (
                f"\n\nCOACH'S RULES — these override the knowledge base above. Always follow:\n{rules_text}"
            )

    try:
        raw = await llm.complete([
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_prompt},
        ])
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Creative var generation failed: {e}")
        return {v: "" for v in needed_vars}


# ── Plan intent handlers (no LLM for query; minimal LLM for change requests) ──

def _parse_plan_date(message: str):
    """Return (date_str, label). date_str is None for week-view requests."""
    msg = message.lower()
    today = date.today()

    if any(k in msg for k in ("this week", "training this week", "sessions this week",
                               "week's plan", "week's training", "weekly")):
        return None, "this week"

    if "tomorrow" in msg:
        d = today + timedelta(days=1)
        return d.isoformat(), "tomorrow"

    day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
               "friday": 4, "saturday": 5, "sunday": 6}
    for day_name, weekday in day_map.items():
        if day_name in msg:
            days_ahead = weekday - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today + timedelta(days=days_ahead)).isoformat(), day_name.capitalize()

    return today.isoformat(), "today"


def _format_session(plan: dict) -> str:
    """Build a compact one-line session descriptor from plan data."""
    sess      = plan.get("session_type", "Run")
    dist      = plan.get("distance_km", "")
    intensity = plan.get("intensity", "")
    rpe       = plan.get("rpe_target", "")
    reps      = plan.get("reps", "")
    rep_dist  = plan.get("rep_distance_m", "")
    duration  = plan.get("duration_min", "")

    if reps and rep_dist:
        metric = f"{reps} × {rep_dist}m"
    elif dist and str(dist) not in ("0", ""):
        metric = f"{dist}km"
    elif duration and str(duration) not in ("0", ""):
        metric = f"{duration}min"
    else:
        metric = ""

    parts = [sess]
    if metric:
        parts.append(metric)
    if intensity:
        parts.append(f"at {intensity}")
    if rpe:
        parts.append(f"(RPE {rpe})")
    return " · ".join(parts)


def _is_next_session_query(message: str) -> bool:
    msg = message.lower()
    return any(p in msg for p in ("next workout", "next run", "next session", "next training",
                                   "when is my next", "upcoming session", "upcoming run",
                                   "upcoming workout"))


async def _handle_plan_query(runner: dict, today_plan, message: str) -> str:
    first      = (runner.get("name") or "there").split()[0]
    runner_id  = runner.get("runner_id", "")

    # "when is my next run?" — find next non-rest session from today/tomorrow
    if _is_next_session_query(message):
        start = date.today().isoformat()
        end   = (date.today() + timedelta(days=21)).isoformat()
        plans = sheets.get_runner_plans(runner_id, from_date=start, to_date=end)
        upcoming = [p for p in plans if str(p.get("day_type", "")).lower() != "rest"]
        if not upcoming:
            return fill_template("plan_no_session", {"first_name": first, "day_label": "the next 3 weeks"})
        plan  = upcoming[0]
        try:
            label = date.fromisoformat(plan["date"]).strftime("%A, %d %b")
        except Exception:
            label = plan["date"]
        session_summary = _format_session(plan)
        coach_notes  = plan.get("coach_notes", "")
        workout_notes = plan.get("workout_notes", "")
        notes        = "\n".join(filter(None, [coach_notes, workout_notes]))
        return fill_template("plan_today_detail", {
            "first_name":      first,
            "day_label":       label,
            "session_summary": session_summary,
            "notes_section":   f"\n\n{notes}" if notes else "",
        })

    # Detail follow-ups ("give me details", "what distance", etc.) — look at today's or tomorrow's plan
    msg_lower = message.lower()
    if any(p in msg_lower for p in ("give me details", "more details", "tell me more about",
                                     "what distance", "how far", "as per plan", "planned distance",
                                     "how many km", "what's the distance", "what is the distance")):
        # Check today first, then tomorrow
        plan = today_plan
        if not plan or str(plan.get("day_type", "")).lower() == "rest":
            plan = sheets.get_plan_by_date(runner_id, (date.today() + timedelta(days=1)).isoformat())
        if not plan:
            # Fall back to next upcoming
            start = (date.today() + timedelta(days=1)).isoformat()
            end   = (date.today() + timedelta(days=14)).isoformat()
            plans = sheets.get_runner_plans(runner_id, from_date=start, to_date=end)
            upcoming = [p for p in plans if str(p.get("day_type", "")).lower() != "rest"]
            plan = upcoming[0] if upcoming else None
        if not plan:
            return fill_template("plan_no_session", {"first_name": first, "day_label": "your next session"})
        try:
            label = date.fromisoformat(plan["date"]).strftime("%A, %d %b")
        except Exception:
            label = plan.get("date", "upcoming")
        session_summary = _format_session(plan)
        coach_notes   = plan.get("coach_notes", "")
        workout_notes = plan.get("workout_notes", "")
        notes         = "\n".join(filter(None, [coach_notes, workout_notes]))
        return fill_template("plan_today_detail", {
            "first_name":      first,
            "day_label":       label,
            "session_summary": session_summary,
            "notes_section":   f"\n\n{notes}" if notes else "",
        })

    date_str, label = _parse_plan_date(message)

    if label == "this week":
        week_start = date.today().isoformat()
        week_end   = (date.today() + timedelta(days=7)).isoformat()
        plans = sheets.get_runner_plans(runner_id, from_date=week_start, to_date=week_end)
        if not plans:
            return fill_template("plan_no_session", {"first_name": first, "day_label": "this week"})

        lines = []
        for p in plans:
            try:
                day_label = date.fromisoformat(p["date"]).strftime("%a %d %b")
            except Exception:
                day_label = p["date"]
            if str(p.get("day_type", "")).lower() == "rest":
                lines.append(f"{day_label}: Rest day")
            else:
                lines.append(f"{day_label}: {_format_session(p)}")

        race_goal     = runner.get("race_goal") or "your goal race"
        weeks_to_race = str(weeks_until(runner.get("race_date") or ""))
        return fill_template("plan_week_view", {
            "first_name":    first,
            "week_plan":     "\n".join(lines),
            "weeks_to_race": weeks_to_race,
            "race_goal":     race_goal,
        })

    # Specific day
    if date_str == date.today().isoformat() and today_plan:
        plan = today_plan
    else:
        plan = sheets.get_plan_by_date(runner_id, date_str)

    if not plan:
        return fill_template("plan_no_session", {"first_name": first, "day_label": label})

    if str(plan.get("day_type", "")).lower() == "rest":
        return fill_template("plan_no_session", {
            "first_name": first,
            "day_label":  f"{label} (it's a scheduled rest day)",
        })

    session_summary = _format_session(plan)
    coach_notes     = plan.get("coach_notes", "")
    workout_notes   = plan.get("workout_notes", "")
    notes           = "\n".join(filter(None, [coach_notes, workout_notes]))
    notes_section   = f"\n\n{notes}" if notes else ""

    return fill_template("plan_today_detail", {
        "first_name":      first,
        "day_label":       label,
        "session_summary": session_summary,
        "notes_section":   notes_section,
    })


async def _handle_plan_change_request(runner: dict, today_plan, message: str,
                                      request_type: str) -> str:
    first     = (runner.get("name") or "there").split()[0]
    runner_id = runner.get("runner_id", "")
    coach_id  = runner.get("coach_id", "")

    # Use LLM to extract a clean one-sentence description of what the runner wants
    try:
        raw_desc = await llm.complete([
            {"role": "system",
             "content": ("Extract the runner's plan change request as one clear sentence. "
                         "Be specific: include the session, the requested change, and the date/day if mentioned. "
                         "Return only the sentence — no prefix, no explanation.")},
            {"role": "user", "content": message},
        ], max_tokens=80)
        description = raw_desc.strip()[:250]
    except Exception:
        description = message[:250]

    date_str, _ = _parse_plan_date(message)
    plan = None
    if date_str:
        plan = today_plan if date_str == date.today().isoformat() else sheets.get_plan_by_date(runner_id, date_str)
    plan_id = (plan.get("plan_id") or plan.get("_id", "")) if plan else ""

    sheets.create_plan_request(
        runner_id=runner_id,
        coach_id=coach_id,
        request_type=request_type,
        description=description,
        session_date=date_str or "",
        plan_id=plan_id,
    )

    if request_type == "reschedule":
        return fill_template("plan_reschedule_flagged", {
            "first_name":            first,
            "reschedule_description": description,
        })
    return fill_template("plan_tweak_flagged", {
        "first_name":        first,
        "tweak_description": description,
    })


# ── Main entry point ──────────────────────────────────────────────────────────

async def select_template_response(
    runner: dict, plan, history: list, message: str, intent: str
) -> str:
    """
    Returns the exact filled template text — same content that would go to WhatsApp.
    Template is chosen by rule; variables filled from data first, LLM only for the rest.
    """
    # Plan intents bypass the template+LLM pipeline — handled by dedicated functions
    if intent == "plan_query":
        return await _handle_plan_query(runner, plan, message)
    if intent == "plan_reschedule":
        return await _handle_plan_change_request(runner, plan, message, "reschedule")
    if intent == "plan_tweak":
        return await _handle_plan_change_request(runner, plan, message, "tweak")

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

    creative = await _fill_creative_vars(needs_llm, runner, plan, message, base, history=history, intent=intent)
    all_vars = {**base, **creative}

    try:
        result = fill_template(template_id, all_vars)
        logger.info(f"Template selected: {template_id} | intent: {intent}")
        return result
    except KeyError as e:
        logger.error(f"Missing variable {e} for template {template_id}, vars={list(all_vars.keys())}")
        return f"{base['first_name']}, I'll pass this to your coach 🙏"
