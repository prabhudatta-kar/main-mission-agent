import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def runner():
    return {
        "runner_id": "RUN_TEST01",
        "name": "Priya Sharma",
        "phone": "9876543210",
        "coach_id": "COACH_A",
        "race_goal": "Half Marathon",
        "race_date": "2026-01-19",
        "weekly_days": "4",
        "injuries": "None",
        "fitness_level": "Intermediate",
        "status": "Active",
        "onboarded": "TRUE",
        "payment_status": "Paid",
        "monthly_fee": "1000",
        "notes": "",
        "start_date": "2025-11-01",
        "prompt_version": "v1",
    }


@pytest.fixture
def unboarded_runner(runner):
    return {**runner, "onboarded": "FALSE", "name": "New Runner"}


@pytest.fixture
def coach():
    return {
        "coach_id": "COACH_A",
        "coach_name": "Coach Test",
        "coach_phone": "+919999999999",
        "active_prompt_version": "v1",
        "system_prompt_v1": "You are a running coach assistant for Main Mission.",
        "active_system_prompt": "You are a running coach assistant for Main Mission.",
        "coaching_style": "Warm and motivational",
        "status": "Active",
    }


@pytest.fixture
def mock_sheets(runner, coach):
    m = MagicMock()
    m.find_runner_by_phone.return_value = runner
    m.find_any_runner_by_phone.return_value = runner
    m.find_coach_by_phone.return_value = None
    m.get_runner.return_value = runner
    m.get_coach_config.return_value = coach
    m.get_active_rules.return_value = []
    m.get_todays_plan.return_value = None
    m.get_last_n_messages.return_value = []
    m.get_all_active_coaches.return_value = [coach]
    m.log_conversation.return_value = None
    m.update_plan_feedback.return_value = None
    m.log_platform_event.return_value = None
    m.create_runner.return_value = "RUN_NEW01"
    m.update_runner.return_value = None
    return m


@pytest.fixture
def mock_llm():
    m = MagicMock()
    m.complete = AsyncMock(return_value="Great job on your run! Keep it up 🏃")
    return m


@pytest.fixture
def mock_whatsapp():
    m = MagicMock()
    m.send_text = AsyncMock(return_value=None)
    m.send_template = AsyncMock(return_value=None)
    return m
