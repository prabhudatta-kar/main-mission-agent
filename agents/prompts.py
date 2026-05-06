from datetime import date


def build_runner_prompt(system_prompt: str, rules: list, runner: dict, plan: dict, history: list, incoming: str) -> list:
    rules_text = "\n".join(f"- {r['rule_derived']}" for r in rules) if rules else "None"

    weeks_to_race = _weeks_to_race(runner.get("race_date"))

    runner_context = f"""RUNNER PROFILE:
Name: {runner.get('name')}
Race goal: {runner.get('race_goal')} ({runner.get('race_date')})
Weeks to race: {weeks_to_race}
Training days per week: {runner.get('weekly_days')}
Fitness level: {runner.get('fitness_level')}
Known issues: {runner.get('injuries') or 'None'}"""

    plan_context = ""
    if plan:
        plan_context = f"""
TODAY'S SESSION:
Type: {plan.get('session_type')}
Distance: {plan.get('distance_km')} km
Intensity: {plan.get('intensity')}
RPE target: {plan.get('rpe_target')}
Coach notes: {plan.get('coach_notes') or 'None'}"""

    history_text = ""
    if history:
        history_text = "\nCONVERSATION HISTORY (most recent last):\n"
        for msg in history:
            role = "Runner" if msg["direction"] == "inbound" else "Agent"
            history_text += f"{role}: {msg['message']}\n"

    full_system = f"""{system_prompt}

COACH RULES (always follow — these override your defaults):
{rules_text}

{runner_context}
{plan_context}
{history_text}
CONTEXT INSTRUCTIONS:
- Read the conversation history carefully before responding. Never ask for information already given.
- If the runner mentions their race, injury, or any profile detail, treat it as the latest ground truth even if it differs from the profile above.
- If the runner references something from a previous message ("like I said", "as I mentioned"), find it in the history and respond accordingly.
- Maintain continuity — your response should feel like an ongoing conversation, not a fresh start."""

    return [
        {"role": "system", "content": full_system},
        {"role": "user", "content": incoming}
    ]


def _weeks_to_race(race_date_str: str) -> str:
    if not race_date_str:
        return "Unknown"
    try:
        race_date = date.fromisoformat(str(race_date_str))
        delta = (race_date - date.today()).days
        return str(max(0, delta // 7))
    except Exception:
        return "Unknown"
