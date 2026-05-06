"""
Prompt structure must always include runner context, rules, history, and today's plan.
If any of these are missing the LLM loses critical context.
"""
import pytest
from agents.prompts import build_runner_prompt


SYSTEM = "You are a running coach assistant."
RUNNER = {
    "name": "Priya Sharma",
    "race_goal": "Half Marathon",
    "race_date": "2026-01-19",
    "weekly_days": "4",
    "fitness_level": "Intermediate",
    "injuries": "Left knee (ITB)",
}
PLAN = {
    "session_type": "Easy Run",
    "distance_km": "6",
    "intensity": "Zone 2",
    "rpe_target": "4-5 out of 10",
    "coach_notes": "Focus on form",
}
RULES = [
    {"rule_derived": "Always recommend rest for knee pain"},
    {"rule_derived": "Use empathy first when runner misses 3+ sessions"},
]
HISTORY = [
    {"direction": "inbound",  "message": "I ran 5km yesterday"},
    {"direction": "outbound", "message": "Great effort! How did it feel?"},
]


def test_returns_list_of_messages():
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, [], "hi")
    assert isinstance(result, list)
    assert result[0]["role"] == "system"
    assert result[-1]["role"] == "user"
    assert result[-1]["content"] == "hi"


def test_system_prompt_is_first():
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, [], "hi")
    assert result[0]["content"].startswith(SYSTEM)


def test_runner_name_in_context():
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, [], "hi")
    system_content = result[0]["content"]
    assert "Priya Sharma" in system_content


def test_race_goal_in_context():
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, [], "hi")
    assert "Half Marathon" in result[0]["content"]


def test_rules_injected():
    result = build_runner_prompt(SYSTEM, RULES, RUNNER, None, [], "hi")
    content = result[0]["content"]
    assert "Always recommend rest for knee pain" in content
    assert "empathy first" in content


def test_todays_plan_injected():
    result = build_runner_prompt(SYSTEM, [], RUNNER, PLAN, [], "hi")
    content = result[0]["content"]
    assert "Easy Run" in content
    assert "Zone 2" in content


def test_no_plan_does_not_crash():
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, [], "hi")
    assert result is not None


def test_history_injected():
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, HISTORY, "how am I doing?")
    content = result[0]["content"]
    assert "I ran 5km yesterday" in content
    assert "Great effort!" in content


def test_incoming_message_is_last_user_message():
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, [], "what pace should I run?")
    assert result[-1] == {"role": "user", "content": "what pace should I run?"}


def test_injuries_in_runner_context():
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, [], "hi")
    assert "ITB" in result[0]["content"]


def test_context_instructions_present():
    """Prompt must always remind LLM to use history and not repeat questions."""
    result = build_runner_prompt(SYSTEM, [], RUNNER, None, HISTORY, "hi")
    assert "Never ask for information already given" in result[0]["content"]
