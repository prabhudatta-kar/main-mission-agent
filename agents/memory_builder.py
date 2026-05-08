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

_BUILD_PROMPT = """You are building a compact coaching memory for an AI running coach.

This runner has no existing memory yet. Analyse their full conversation history and produce a structured summary.

Runner profile:
{profile}

Full conversation history (oldest → newest):
{history}

Return ONLY valid JSON (no markdown):
{{
  "summary": "2-3 sentence overview: who they are, race goal, training background, general attitude",
  "known_issues": "injuries, niggles, recurring problems — be specific. 'None' if none.",
  "strengths": "what they do well — consistency, attitude, specific fitness strengths",
  "coaching_notes": "communication style, what motivates them, what to push on, what to back off",
  "recent_form": "last 2 weeks: sessions completed vs missed, mood/energy, notable runs or setbacks",
  "watch_points": "warning signs, patterns that lead to skipping, injury triggers"
}}"""

_UPDATE_PROMPT = """You are updating a compact coaching memory for an AI running coach.

Do NOT recreate the memory from scratch. Read the existing memory, then refine or append based only on what's new.

Existing memory (accurate as of {last_updated}):
{existing_memory}

Runner profile (latest):
{profile}

New conversations since last update:
{new_history}

Instructions:
- Keep existing memory fields intact unless new conversations contradict or update them.
- Update "recent_form" to reflect the new period.
- Append to "known_issues" only if new injuries/problems mentioned.
- Refine "coaching_notes" / "watch_points" only if new patterns emerge.
- Keep all fields concise — this is a reference doc, not a report.

Return ONLY valid JSON with the same keys (no markdown):
{{
  "summary": "...",
  "known_issues": "...",
  "strengths": "...",
  "coaching_notes": "...",
  "recent_form": "...",
  "watch_points": "..."
}}"""


async def build_all_runner_memories():
    """Update memory for every active runner. Run nightly."""
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

    existing = sheets.get_runner_memory(runner_id)
    last_updated = existing.get("last_updated", "") if existing else ""

    # Only fetch messages since the last memory update (or all if no memory yet)
    all_convos = sheets.get_all_runner_conversations(runner_id, limit=300)
    if not all_convos:
        logger.info(f"Memory builder: no conversations for {runner_id}, skipping")
        return

    if existing and last_updated:
        new_convos = [m for m in all_convos if m.get("timestamp", "") > last_updated]
    else:
        new_convos = all_convos

    if existing and not new_convos:
        logger.info(f"Memory builder: no new messages for {runner_id} since {last_updated}, skipping")
        return

    profile = {
        "name":          runner.get("name", ""),
        "race_goal":     runner.get("race_goal", ""),
        "race_date":     runner.get("race_date", ""),
        "weekly_days":   runner.get("weekly_days", ""),
        "fitness_level": runner.get("fitness_level", ""),
        "injuries":      runner.get("injuries", ""),
        "start_date":    runner.get("start_date", ""),
    }

    def _format(convos: list) -> str:
        lines = []
        for m in convos:
            text = (m.get("message") or "").strip()
            if not text:
                continue
            prefix = "Runner" if m.get("direction") == "inbound" else "Coach AI"
            ts     = m.get("timestamp", "")[:10]
            lines.append(f"[{ts}] {prefix}: {text[:300]}")
        return "\n".join(lines)[:8000]

    if existing:
        # Incremental update — pass existing memory + only new messages
        existing_clean = {k: v for k, v in existing.items()
                          if k not in ("runner_id", "last_updated", "_id")}
        prompt = (
            _UPDATE_PROMPT
            .replace("{last_updated}",    last_updated)
            .replace("{existing_memory}", json.dumps(existing_clean, indent=2))
            .replace("{profile}",         json.dumps(profile, indent=2))
            .replace("{new_history}",     _format(new_convos))
        )
        system_msg = "Update the runner memory using only new information. Return only valid JSON."
        n_new = len(new_convos)
        logger.info(f"Memory builder: updating {runner_id} with {n_new} new messages")
    else:
        # First build — use all conversations
        prompt = (
            _BUILD_PROMPT
            .replace("{profile}", json.dumps(profile, indent=2))
            .replace("{history}", _format(all_convos))
        )
        system_msg = "Build compact, accurate runner memory. Return only valid JSON."
        logger.info(f"Memory builder: first build for {runner_id} with {len(all_convos)} messages")

    raw = await llm.complete([
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": prompt},
    ], model=OBSERVATIONS_MODEL, max_tokens=1000)

    raw    = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    memory = json.loads(raw)
    sheets.save_runner_memory(runner_id, memory)
    logger.info(f"Memory saved for {runner_id} ({runner.get('name')})")
