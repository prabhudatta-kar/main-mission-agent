"""
Coach Watcher — nightly job per coach that reads their runners' conversations,
identifies patterns in responses and coaching style gaps, then sends 1-2
targeted questions to the coach via WhatsApp to refine their AI rules.

Coach replies are processed by handle_coach_message → saved as new rules.
"""
import json
import logging
from datetime import datetime, timedelta

import pytz

from integrations.firebase_db import sheets
from integrations.llm import llm
from integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")

_SYSTEM_PROMPT = """You are helping improve an AI running coach's personalised style for a specific coach.

You'll receive:
1. The coach's current rules and system prompt
2. A sample of today's runner conversations

Your job is to generate 1-2 short, specific questions to ask the coach so you can better mirror their real coaching style. Focus on:
- Moments where the AI's tone or advice might differ from the coach's actual style
- Patterns in runner questions that the coach hasn't explicitly covered yet
- How the coach would personally handle a specific situation from today

Rules:
- Questions must be short and WhatsApp-friendly (no bullet lists, just natural sentences)
- Ask about concrete situations from today's conversations, not hypotheticals
- Don't ask more than 2 questions
- If today's conversations were routine and well-handled, send a brief positive note + 1 forward-looking question
- If there's nothing useful to ask, return null

Return ONLY valid JSON (no markdown):
{
  "should_send": true,
  "message": "the WhatsApp message to send to the coach (2-4 sentences max)"
}
OR
{
  "should_send": false,
  "reason": "why nothing is worth asking today"
}"""


async def run_coach_watcher():
    """For each active coach, analyse runner conversations and send style questions."""
    logger.info("Coach watcher: starting")
    for coach in sheets.get_all_active_coaches():
        try:
            await _process_coach(coach)
        except Exception as e:
            logger.error(f"Coach watcher failed for {coach.get('coach_id')}: {e}", exc_info=True)


async def _process_coach(coach: dict):
    coach_id = coach["coach_id"]
    coach_phone = coach.get("coach_phone", "")
    coach_name = coach.get("name", "Coach")
    first = coach_name.split()[0]

    runners = sheets.get_coach_runners(coach_id)
    if not runners:
        return

    convos = _get_runner_conversations(runners, hours=24)
    if not convos:
        logger.info(f"Coach watcher: no conversations for coach {coach_id}")
        return

    rules = sheets.get_all_coach_rules(coach_id)
    config = sheets.get_coach_config(coach_id)
    active_version = config.get("active_prompt_version", "v1") if config else "v1"
    current_prompt = (config or {}).get(f"system_prompt_{active_version}", "") if config else ""

    context = _build_context(convos, rules, current_prompt)

    raw = await llm.complete([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": context},
    ], max_tokens=600)

    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    result = json.loads(raw)

    if not result.get("should_send"):
        logger.info(f"Coach watcher: nothing to ask coach {coach_id} — {result.get('reason','')}")
        return

    message = result["message"]
    full_message = f"Hi {first} 👋 Quick coaching question from your AI:\n\n{message}\n\nJust reply here and I'll update your settings."

    await whatsapp.send_text(coach_phone, full_message)
    logger.info(f"Coach watcher: sent question to coach {coach_id}")

    sheets.log_platform_event(
        "coach_watcher", "", coach_id,
        f"Sent coaching style question: {message[:100]}"
    )


def _get_runner_conversations(runners: list, hours: int = 24) -> list:
    cutoff = (datetime.now(_IST) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    runner_ids = {r["runner_id"] for r in runners}
    all_msgs = sheets._stream(sheets._col("conversations"))
    recent = [
        m for m in all_msgs
        if m.get("runner_id") in runner_ids
        and m.get("timestamp", "") >= cutoff
        and m.get("message")
    ]
    recent.sort(key=lambda m: m.get("timestamp", ""))
    return recent


def _build_context(convos: list, rules: list, current_prompt: str) -> str:
    # Format conversations
    by_runner: dict = {}
    for m in convos:
        rid = m.get("runner_id", "unknown")
        by_runner.setdefault(rid, []).append(m)

    convo_block = []
    for rid, thread in by_runner.items():
        lines = [f"[Runner {rid}]"]
        for m in thread:
            prefix = "AI →" if m["direction"] == "outbound" else "Runner:"
            lines.append(f"  {prefix} {m.get('message','')[:200]}")
        convo_block.append("\n".join(lines))

    rules_text = "\n".join(
        f"- {r.get('rule_derived','')}" for r in rules[:20] if r.get("status") == "Active"
    ) or "No rules yet."

    return f"""Coach's current style rules:
{rules_text}

Coach's current system prompt:
{current_prompt[:800] or 'Not set yet.'}

Today's conversations:
{chr(10).join(convo_block)[:6000]}"""
