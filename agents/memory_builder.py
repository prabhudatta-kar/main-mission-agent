"""
Runner Memory Builder — nightly job that summarises each runner's full
conversation history into a compact memory document in Firebase.

The memory is read by the coaching agent on every reply, giving it
long-term context without fetching hundreds of raw messages.

Memory document (runner_memory/{runner_id}):
  summary         — who this runner is, their patterns and tendencies
  known_issues    — injuries, recurring struggles, things to watch
  strengths       — what they do well, what motivates them
  coaching_notes  — what's working, what to push on, communication style
  recent_form     — last 2 weeks: sessions completed, mood, feedback
  last_updated    — timestamp
"""
import json
import logging

from config.settings import OBSERVATIONS_MODEL
from integrations.firebase_db import sheets
from integrations.llm import llm

logger = logging.getLogger(__name__)

_PROMPT = """You are building a compact coaching memory for an AI running coach.

Analyse all conversations between the AI coach and this runner, then produce a concise, structured summary that the coach can use on every future reply to personalise responses.

Runner profile:
{profile}

Full conversation history (oldest → newest):
{history}

Return ONLY valid JSON (no markdown):
{{
  "summary": "2-3 sentence overview: who they are, their race goal, training background, general attitude",
  "known_issues": "injuries, physical niggles, recurring problems — be specific (e.g. 'left knee pain after runs over 12km'). 'None' if none.",
  "strengths": "what they do well — consistency, attitude, specific fitness strengths",
  "coaching_notes": "communication style preferences, what motivates them, what to push on, what to back off",
  "recent_form": "last 2 weeks summary: sessions completed vs missed, mood/energy level, any notable runs or setbacks",
  "watch_points": "things to monitor: warning signs, patterns that lead to skipping, injury triggers"
}}"""


async def build_all_runner_memories():
    """Build memory for every active runner. Run nightly."""
    runners = sheets.get_all_active_runners()
    logger.info(f"Memory builder: starting for {len(runners)} runners")
    for runner in runners:
        try:
            await build_runner_memory(runner)
        except Exception as e:
            logger.error(f"Memory build failed for {runner['runner_id']}: {e}", exc_info=True)
    logger.info("Memory builder: complete")


async def build_runner_memory(runner: dict):
    runner_id = runner["runner_id"]

    convos = sheets.get_all_runner_conversations(runner_id, limit=200)
    if not convos:
        logger.info(f"Memory builder: no conversations for {runner_id}, skipping")
        return

    history_lines = []
    for m in convos:
        direction = m.get("direction", "")
        text      = (m.get("message") or "").strip()
        if not text:
            continue
        prefix = "Runner" if direction == "inbound" else "Coach AI"
        ts     = m.get("timestamp", "")[:10]   # just the date
        history_lines.append(f"[{ts}] {prefix}: {text[:300]}")

    history_text = "\n".join(history_lines)[:10000]   # cap token cost

    profile = {
        "name":          runner.get("name", ""),
        "race_goal":     runner.get("race_goal", ""),
        "race_date":     runner.get("race_date", ""),
        "weekly_days":   runner.get("weekly_days", ""),
        "fitness_level": runner.get("fitness_level", ""),
        "injuries":      runner.get("injuries", ""),
        "start_date":    runner.get("start_date", ""),
    }

    prompt = _PROMPT.replace("{profile}", json.dumps(profile, indent=2)) \
                    .replace("{history}", history_text)

    raw = await llm.complete([
        {"role": "system", "content": "You are a coaching analyst. Build compact, accurate runner memory. Return only valid JSON."},
        {"role": "user",   "content": prompt},
    ], model=OBSERVATIONS_MODEL, max_tokens=1000)

    raw    = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    memory = json.loads(raw)
    sheets.save_runner_memory(runner_id, memory)
    logger.info(f"Memory built for {runner_id} ({runner.get('name')}) — {len(history_lines)} messages processed")
