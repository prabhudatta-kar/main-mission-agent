"""
Coach Watcher — nightly job per coach that reads their runners' conversations,
identifies patterns and coaching style gaps, saves observations to Firebase,
and sends 1-2 targeted questions to the coach via WhatsApp.

Observations are stored in the `coach_observations` collection and viewable
at /coachobservations/{coach_id}.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta

import pytz

from config.settings import OBSERVATIONS_MODEL
from integrations.firebase_db import sheets
from integrations.llm import llm
from integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")

_SYSTEM_PROMPT = """You are a coaching quality analyst for Main Mission, a WhatsApp AI running coaching platform.

You will receive:
1. A coach's current rules and system prompt
2. Today's conversations between the AI and their runners

Produce a structured daily observation for this coach. Identify:
- Patterns in runner behaviour (common questions, mood, struggles)
- Moments where the AI's tone or advice might differ from this coach's style
- Gaps in coverage — situations the coach hasn't given rules for
- What went well

Then craft 1-2 short WhatsApp-friendly questions (no bullet lists, natural sentences) to send to the coach
to better understand their style for the situations you found.
If conversations were routine and well-handled, send a positive note + one forward-looking question.
If there is genuinely nothing useful to ask, set should_send to false.

Return ONLY valid JSON (no markdown):
{
  "summary": "2-3 sentence overview of today's coaching activity",
  "patterns": [
    {"title": "short label", "description": "what you noticed", "frequency": "once|recurring"}
  ],
  "style_gaps": [
    {"situation": "describe it", "current_ai_approach": "what the AI did", "question_for_coach": "what you'd ask"}
  ],
  "wins": ["short win description"],
  "should_send": true,
  "coach_message": "the WhatsApp message to send — 2-4 sentences, conversational"
}"""


async def run_coach_watcher():
    """For each active coach, analyse runner conversations, save observation, send question."""
    logger.info("Coach watcher: starting")
    for coach in sheets.get_all_active_coaches():
        try:
            await _process_coach(coach)
        except Exception as e:
            logger.error(f"Coach watcher failed for {coach.get('coach_id')}: {e}", exc_info=True)


async def _process_coach(coach: dict):
    coach_id    = coach["coach_id"]
    coach_phone = coach.get("coach_phone", "")
    first       = (coach.get("name") or "Coach").split()[0]

    runners = sheets.get_coach_runners(coach_id)
    if not runners:
        return

    convos = _get_runner_conversations(runners, hours=24)
    if not convos:
        logger.info(f"Coach watcher: no conversations for coach {coach_id}")
        return

    rules          = sheets.get_all_coach_rules(coach_id)
    config         = sheets.get_coach_config(coach_id) or {}
    active_version = config.get("active_prompt_version", "v1")
    current_prompt = config.get(f"system_prompt_{active_version}", "")

    context = _build_context(convos, runners, rules, current_prompt)

    raw = await llm.complete([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": context},
    ], model=OBSERVATIONS_MODEL, max_tokens=1500)

    raw    = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    result = json.loads(raw)

    # Always save to Firebase regardless of whether we send
    obs_id = _save_observation(coach_id, result, len(convos), len(runners))
    logger.info(f"Coach watcher: saved observation {obs_id} for coach {coach_id}")

    if not result.get("should_send"):
        logger.info(f"Coach watcher: nothing to send for coach {coach_id}")
        return

    coach_msg  = result.get("coach_message", "")
    full_msg   = f"Hi {first} 👋 Quick coaching question from your AI:\n\n{coach_msg}\n\nJust reply here and I'll update your settings."

    await whatsapp.send_text(coach_phone, full_msg)
    logger.info(f"Coach watcher: sent question to coach {coach_id}")

    # Mark that message was sent, so we can show it in the dashboard
    sheets._col("coach_observations").document(obs_id).update({"message_sent": full_msg})


def _save_observation(coach_id: str, result: dict, convo_count: int, runner_count: int) -> str:
    obs_id = f"COBS_{str(uuid.uuid4())[:8].upper()}"
    sheets._col("coach_observations").document(obs_id).set({
        "obs_id":        obs_id,
        "coach_id":      coach_id,
        "created_at":    datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
        "date":          datetime.now(_IST).strftime("%Y-%m-%d"),
        "convo_count":   convo_count,
        "runner_count":  runner_count,
        "summary":       result.get("summary", ""),
        "patterns":      result.get("patterns", []),
        "style_gaps":    result.get("style_gaps", []),
        "wins":          result.get("wins", []),
        "message_sent":  "",   # filled in after sending
        "coach_reply":   "",   # filled in when coach replies via WhatsApp
    })
    return obs_id


def _get_runner_conversations(runners: list, hours: int = 24) -> list:
    cutoff     = (datetime.now(_IST) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    runner_ids = {r["runner_id"] for r in runners}
    all_msgs   = sheets._stream(sheets._col("conversations"))
    recent     = [
        m for m in all_msgs
        if m.get("runner_id") in runner_ids
        and m.get("timestamp", "") >= cutoff
        and m.get("message")
    ]
    recent.sort(key=lambda m: m.get("timestamp", ""))
    return recent


def _build_context(convos: list, runners: list, rules: list, current_prompt: str) -> str:
    name_map = {r["runner_id"]: r.get("name", r["runner_id"]) for r in runners}

    by_runner: dict = {}
    for m in convos:
        rid = m.get("runner_id", "unknown")
        by_runner.setdefault(rid, []).append(m)

    convo_block = []
    for rid, thread in by_runner.items():
        name  = name_map.get(rid, rid)
        lines = [f"[{name}]"]
        for m in thread:
            prefix = "AI →" if m["direction"] == "outbound" else "Runner:"
            lines.append(f"  {prefix} {m.get('message','')[:250]}")
        convo_block.append("\n".join(lines))

    rules_text = "\n".join(
        f"- {r.get('rule_derived','')}" for r in rules[:20] if r.get("status") == "Active"
    ) or "No rules set yet."

    return f"""Coach's current style rules:
{rules_text}

Coach's system prompt:
{current_prompt[:800] or 'Not set yet.'}

Today's conversations ({len(runners)} runners, {len(convos)} messages):
{chr(10).join(convo_block)[:7000]}"""


def get_coach_observations(coach_id: str, limit: int = 30) -> list:
    obs = sheets._stream(
        sheets._col("coach_observations").where("coach_id", "==", coach_id)
    )
    obs.sort(key=lambda o: o.get("created_at", ""), reverse=True)
    return obs[:limit]
