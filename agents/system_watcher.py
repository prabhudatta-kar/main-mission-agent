"""
System Watcher — nightly job that reads all conversations and generates
structured improvement observations with one-click-applicable fixes.

Saves to Firebase `system_observations` collection.
Visible at /sysobservations.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta

import pytz

from config.settings import OBSERVATIONS_MODEL
from integrations.firebase_db import sheets
from integrations.llm import llm

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")

_ANALYSIS_PROMPT = """You are a product quality analyst for Main Mission, a WhatsApp-based AI running coaching platform.

Analyse the conversations provided. Identify:
1. Response quality issues — generic, hallucinated, wrong-tone, repetitive replies
2. Template gaps — intents or questions that lack a good template
3. Conversation flow problems — agent losing context, inconsistent persona
4. Missed opportunities — moments where a better reply was possible
5. Wins — things that worked well

Return ONLY valid JSON (no markdown):
{
  "summary": "2-3 sentence overview",
  "issues": [
    {
      "type": "response_quality|template_gap|flow_problem|missed_opportunity",
      "severity": "high|medium|low",
      "title": "short title",
      "description": "what happened and why it's a problem",
      "example": "quote or paraphrase from conversation"
    }
  ],
  "wins": [{"title": "...", "description": "..."}],
  "top_priority": "single most important thing to fix"
}"""

_FIX_PROMPT = """You are an AI prompt engineer for Main Mission, a WhatsApp running coaching platform.

You have identified issues in today's agent conversations. For each issue, generate a concrete one-click fix.

Available prompt targets you can patch:
{prompt_catalog}

Fix types:
- "prompt_update": rewrite one of the prompts above to address the issue
- "rule_add": add a plain-text coaching rule (stored in Firebase, injected into agent context)

For "prompt_update" fixes, write the COMPLETE new prompt text (not a diff — the full replacement).
For "rule_add" fixes, write the exact rule text to add.

Issues to fix:
{issues_json}

Current prompt contents:
{current_prompts}

Return ONLY valid JSON array (no markdown):
[
  {
    "issue_title": "title of the issue this fixes",
    "fix_type": "prompt_update|rule_add",
    "target_id": "onboarding|creative_vars_system|creative_vars_user|rule",
    "target_label": "Human readable name",
    "description": "what this fix does in 1 sentence",
    "new_content": "the full new prompt text or rule text"
  }
]"""


async def run_system_watcher():
    """Analyse conversations, save observations + generated fixes to Firebase."""
    logger.info("System watcher: starting analysis")
    try:
        convos = _get_recent_conversations(hours=24)
        if not convos:
            logger.info("System watcher: no conversations to analyse")
            return

        analysis_text = _format_conversations(convos)

        # Step 1 — identify issues
        raw = await llm.complete([
            {"role": "system", "content": _ANALYSIS_PROMPT},
            {"role": "user",   "content": f"Conversations to analyse:\n\n{analysis_text}"},
        ], model=OBSERVATIONS_MODEL, max_tokens=2000)
        raw    = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)

        # Step 2 — generate structured fixes for each issue
        fixes = []
        issues = result.get("issues", [])
        if issues:
            fixes = await _generate_fixes(issues)

        _save_observation(result, fixes, len(convos))
        logger.info(f"System watcher: {len(issues)} issues, {len(fixes)} fixes, {len(result.get('wins',[]))} wins")

    except Exception as e:
        logger.error(f"System watcher failed: {e}", exc_info=True)


async def _generate_fixes(issues: list) -> list:
    from agents.prompt_store import get_prompt, list_prompt_ids
    prompt_ids = list_prompt_ids()
    catalog    = "\n".join(f"  - {pid}" for pid in prompt_ids)
    current    = "\n\n".join(
        f"=== {pid} ===\n{get_prompt(pid)[:800]}" for pid in prompt_ids
    )

    try:
        # Use .replace() instead of .format() — issues_json contains { } which
        # confuse str.format() into raising KeyError on JSON object keys.
        user_content = (
            _FIX_PROMPT
            .replace("{prompt_catalog}", catalog)
            .replace("{issues_json}", json.dumps(issues, indent=2))
            .replace("{current_prompts}", current)
        )
        raw = await llm.complete([
            {"role": "system", "content": "You are an expert AI prompt engineer. Generate minimal, targeted fixes. Return only valid JSON array."},
            {"role": "user",   "content": user_content},
        ], model=OBSERVATIONS_MODEL, max_tokens=4000)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        fixes = json.loads(raw)
        if not isinstance(fixes, list):
            fixes = [fixes]
        # Attach current prompt as old_content so the UI can show a diff
        current_prompts = {pid: get_prompt(pid) for pid in prompt_ids}
        for f in fixes:
            if f.get("fix_type") == "prompt_update":
                f["old_content"] = current_prompts.get(f.get("target_id", ""), "")
            f.setdefault("old_content", "")
            f.setdefault("applied", False)
            f.setdefault("applied_at", None)
            f.setdefault("undo_snapshot", None)
        return fixes
    except Exception as e:
        logger.warning(f"Fix generation failed: {e}")
        return []


def _get_recent_conversations(hours: int = 24) -> list:
    cutoff = (datetime.now(_IST) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    all_msgs = sheets._stream(sheets._col("conversations"))
    recent = [m for m in all_msgs if m.get("timestamp", "") >= cutoff and m.get("message")]
    recent.sort(key=lambda m: m.get("timestamp", ""))
    return recent


def _format_conversations(msgs: list) -> str:
    by_runner: dict = {}
    for m in msgs:
        rid = m.get("runner_id", "unknown")
        by_runner.setdefault(rid, []).append(m)

    runners  = sheets.get_all_active_runners()
    name_map = {r["runner_id"]: r.get("name", "") for r in runners}

    blocks = []
    for rid, thread in by_runner.items():
        name  = name_map.get(rid, rid)
        lines = [f"[Runner: {name}]"]
        for m in thread:
            prefix = "→ Agent" if m["direction"] == "outbound" else "← Runner"
            lines.append(f"  {prefix}: {m.get('message','')[:300]}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)[:12000]


def _save_observation(result: dict, fixes: list, convo_count: int):
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
        "fixes":        fixes,
    })
    return obs_id


def get_recent_observations(limit: int = 14) -> list:
    obs = sheets._stream(sheets._col("system_observations"))
    obs.sort(key=lambda o: o.get("created_at", ""), reverse=True)
    return obs[:limit]
