"""
System Watcher — nightly job that reads all conversations and generates
structured improvement observations for the dev team.

Saves to Firebase `system_observations` collection.
Visible at /sysobservations.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta

import pytz

from integrations.firebase_db import sheets
from integrations.llm import llm

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")

_SYSTEM_PROMPT = """You are a product quality analyst for Main Mission, a WhatsApp-based AI running coaching platform.

Analyse the last 24 hours of conversations between the AI agent and runners. Identify:
1. Response quality issues — generic, off-topic, wrong-tone, repetitive, or hallucinated replies
2. Template gaps — common intents or questions that don't have a good template
3. Conversation flow problems — agent losing context, inconsistent persona, awkward transitions
4. Missed opportunities — moments where a great coaching reply was possible but wasn't delivered
5. Wins — things that went really well that we should preserve

Return ONLY valid JSON in exactly this structure (no markdown):
{
  "summary": "2-3 sentence overview of today's conversations",
  "issues": [
    {
      "type": "response_quality|template_gap|flow_problem|missed_opportunity",
      "severity": "high|medium|low",
      "title": "short title",
      "description": "what happened and why it's a problem",
      "example": "quote or paraphrase from conversation",
      "suggested_fix": "concrete action to take"
    }
  ],
  "wins": [
    {
      "title": "short title",
      "description": "what went well"
    }
  ],
  "top_priority": "single most important thing to fix today"
}"""


async def run_system_watcher():
    """Analyse yesterday's conversations and save observations to Firebase."""
    logger.info("System watcher: starting analysis")
    try:
        convos = _get_recent_conversations(hours=24)
        if not convos:
            logger.info("System watcher: no conversations to analyse")
            return

        analysis_text = _format_conversations(convos)
        raw = await llm.complete([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": f"Conversations to analyse:\n\n{analysis_text}"},
        ], max_tokens=2000)

        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)
        _save_observation(result, len(convos))
        logger.info(f"System watcher: saved observation — {len(result.get('issues',[]))} issues, {len(result.get('wins',[]))} wins")

    except Exception as e:
        logger.error(f"System watcher failed: {e}", exc_info=True)


def _get_recent_conversations(hours: int = 24) -> list:
    cutoff = (datetime.now(_IST) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    all_msgs = sheets._stream(sheets._col("conversations"))
    recent = [m for m in all_msgs if m.get("timestamp", "") >= cutoff and m.get("message")]
    recent.sort(key=lambda m: m.get("timestamp", ""))
    return recent


def _format_conversations(msgs: list) -> str:
    """Group by runner and format as readable dialogue."""
    by_runner: dict = {}
    for m in msgs:
        rid = m.get("runner_id", "unknown")
        by_runner.setdefault(rid, []).append(m)

    runners = sheets.get_all_active_runners()
    name_map = {r["runner_id"]: r.get("name", rid) for r in runners}

    blocks = []
    for rid, thread in by_runner.items():
        name = name_map.get(rid, rid)
        lines = [f"[Runner: {name}]"]
        for m in thread:
            direction = "→ Runner" if m["direction"] == "outbound" else "← Runner"
            lines.append(f"  {direction}: {m.get('message','')[:300]}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)[:12000]  # cap context size


def _save_observation(result: dict, convo_count: int):
    obs_id = f"OBS_{str(uuid.uuid4())[:8].upper()}"
    sheets._col("system_observations").document(obs_id).set({
        "obs_id":       obs_id,
        "created_at":   datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S"),
        "date":         datetime.now(_IST).strftime("%Y-%m-%d"),
        "convo_count":  convo_count,
        "summary":      result.get("summary", ""),
        "issues":       result.get("issues", []),
        "wins":         result.get("wins", []),
        "top_priority": result.get("top_priority", ""),
    })


def get_recent_observations(limit: int = 14) -> list:
    obs = sheets._stream(sheets._col("system_observations"))
    obs.sort(key=lambda o: o.get("created_at", ""), reverse=True)
    return obs[:limit]
