import json
import logging

from integrations.llm import llm
from templates.catalog import template_menu, fill_template, TEMPLATES

logger = logging.getLogger(__name__)

_SELECTION_SYSTEM = """You select the right WhatsApp message template for a running coach AI assistant and fill in the variables.

Available templates:
{template_menu}

Rules:
- Pick the single best-matching template based on the scenario description.
- Fill ALL variables for that template. Be specific — use the runner's name, actual numbers, race name.
- Keep variable values short (1 sentence max per variable). No markdown.
- For "answer" or "observation" variables: be direct and personalised, 1-2 sentences.
- For "extra_note": either a brief tip or empty string "".
- Always use the runner's first name only.
- Return ONLY valid JSON — no explanation, no markdown fences."""

_SELECTION_USER = """Runner profile:
{runner_profile}

Today's session: {todays_plan}

Conversation history (last 5):
{history}

Runner's message: "{message}"

Return JSON:
{{
  "template_id": "<id from the list>",
  "variables": {{
    "<var1>": "<value>",
    "<var2>": "<value>"
  }}
}}"""


async def select_template_response(
    runner: dict,
    plan,
    history: list,
    message: str,
    intent: str,
) -> str:
    """
    Uses the LLM to pick the right template and fill variables.
    Returns the filled message string ready to send.
    Falls back to question_general if selection fails.
    """
    runner_profile = (
        f"Name: {runner.get('name', '')}\n"
        f"Race goal: {runner.get('race_goal', 'Unknown')}\n"
        f"Race date: {runner.get('race_date', 'Unknown')}\n"
        f"Fitness level: {runner.get('fitness_level', 'Unknown')}\n"
        f"Injuries: {runner.get('injuries', 'None')}"
    )

    plan_text = "Rest day" if not plan else (
        f"{plan.get('session_type', '')} — {plan.get('distance_km', '')}km "
        f"at {plan.get('intensity', '')} (RPE {plan.get('rpe_target', '')})"
    )

    history_text = "\n".join(
        f"{'Runner' if m['direction'] == 'inbound' else 'Agent'}: {m['message']}"
        for m in history[-5:]
    ) if history else "No prior messages."

    messages = [
        {"role": "system", "content": _SELECTION_SYSTEM.format(template_menu=template_menu())},
        {"role": "user", "content": _SELECTION_USER.format(
            runner_profile=runner_profile,
            todays_plan=plan_text,
            history=history_text,
            message=message,
        )},
    ]

    try:
        raw = await llm.complete(messages, max_tokens=300)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        selection = json.loads(raw)

        template_id = selection["template_id"]
        variables = selection["variables"]

        # Validate the template exists
        if template_id not in TEMPLATES:
            logger.warning(f"LLM selected unknown template '{template_id}', falling back")
            return _fallback(runner, message)

        return fill_template(template_id, variables)

    except Exception as e:
        logger.warning(f"Template selection failed: {e}. Falling back to general response.")
        return _fallback(runner, message)


def _fallback(runner: dict, message: str) -> str:
    first_name = runner.get("name", "there").split()[0]
    return f"{first_name}, I'll pass your message to your coach. They'll be in touch soon 🙏"
