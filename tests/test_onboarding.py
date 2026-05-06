"""
Onboarding flow requirements:
- LLM drives the conversation (not hardcoded questions)
- Completion triggers on [COMPLETE] or when all 5 fields are extractable
- Completion saves runner to Sheets exactly once
- Prefilled fields are not re-asked
- After completion, phone resolves as a runner (not unknown)
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, call
from agents.onboarding_agent import (
    start_onboarding, is_onboarding, handle_onboarding, _sessions
)


def _clear_sessions():
    _sessions.clear()


@pytest.fixture(autouse=True)
def clean_sessions():
    _sessions.clear()
    yield
    _sessions.clear()


# ── session management ────────────────────────────────────────────────────────

def test_start_onboarding_creates_session():
    start_onboarding("+919876543210", "COACH_A", name="Arjun")
    assert is_onboarding("+919876543210")


def test_is_onboarding_false_for_unknown():
    assert not is_onboarding("+910000000000")


def test_start_onboarding_with_prefilled_includes_note():
    start_onboarding("+919876543210", "COACH_A", prefilled={"race": "Mumbai Marathon"})
    session = _sessions["+919876543210"]
    assert "Mumbai Marathon" in session["system"]


def test_start_onboarding_clears_history():
    start_onboarding("+919876543210", "COACH_A")
    assert _sessions["+919876543210"]["history"] == []


# ── LLM drives the conversation ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_onboarding_calls_llm():
    start_onboarding("+919876543210", "COACH_A", name="Arjun")
    with patch("agents.onboarding_agent.llm") as mock_llm:
        mock_llm.complete = AsyncMock(return_value="What race are you training for?")
        response = await handle_onboarding("+919876543210", "hi")
    assert response == "What race are you training for?"
    mock_llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_handle_onboarding_builds_history():
    start_onboarding("+919876543210", "COACH_A", name="Arjun")
    with patch("agents.onboarding_agent.llm") as mock_llm:
        mock_llm.complete = AsyncMock(return_value="What race are you training for?")
        await handle_onboarding("+919876543210", "hi")
        await handle_onboarding("+919876543210", "Ladakh Marathon")

    session = _sessions["+919876543210"]
    user_messages = [m for m in session["history"] if m["role"] == "user"]
    assert len(user_messages) == 2
    assert user_messages[1]["content"] == "Ladakh Marathon"


# ── completion triggers ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_triggered_by_marker(mock_sheets):
    start_onboarding("+919876543210", "COACH_A", name="Arjun")
    with patch("agents.onboarding_agent.llm") as mock_llm, \
         patch("agents.onboarding_agent.sheets", mock_sheets), \
         patch("agents.onboarding_agent._extract_profile", new_callable=AsyncMock) as mock_extract:
        mock_llm.complete = AsyncMock(return_value="All done! [COMPLETE]")
        mock_extract.return_value = {
            "race_goal": "Ladakh Marathon",
            "race_date": "2026-09-15",
            "weekly_days": 3,
            "injuries": "None",
            "fitness_level": "Beginner",
        }
        await handle_onboarding("+919876543210", "5km per week")

    mock_sheets.create_runner.assert_called_once()
    assert not is_onboarding("+919876543210")  # session cleared


@pytest.mark.asyncio
async def test_complete_triggered_by_profile_check(mock_sheets):
    """Even without [COMPLETE], completion should fire if all 5 fields extractable."""
    start_onboarding("+919876543210", "COACH_A", name="Arjun")
    # Simulate 5 user messages already in session
    session = _sessions["+919876543210"]
    for i in range(5):
        session["history"].append({"role": "user", "content": f"answer {i}"})

    with patch("agents.onboarding_agent.llm") as mock_llm, \
         patch("agents.onboarding_agent.sheets", mock_sheets), \
         patch("agents.onboarding_agent._extract_profile", new_callable=AsyncMock) as mock_extract, \
         patch("agents.onboarding_agent._is_profile_complete", new_callable=AsyncMock) as mock_check:
        mock_llm.complete = AsyncMock(return_value="Great, I think we have everything!")
        mock_check.return_value = True
        mock_extract.return_value = {
            "race_goal": "Ladakh Marathon",
            "race_date": "2026-09-15",
            "weekly_days": 3,
            "injuries": "None",
            "fitness_level": "Beginner",
        }
        await handle_onboarding("+919876543210", "per week")

    mock_sheets.create_runner.assert_called_once()
    assert not is_onboarding("+919876543210")


@pytest.mark.asyncio
async def test_create_runner_called_with_correct_fields(mock_sheets):
    start_onboarding("+919876543210", "COACH_A", name="Arjun Singh")
    with patch("agents.onboarding_agent.llm") as mock_llm, \
         patch("agents.onboarding_agent.sheets", mock_sheets), \
         patch("agents.onboarding_agent._extract_profile", new_callable=AsyncMock) as mock_extract:
        mock_llm.complete = AsyncMock(return_value="You're all set! [COMPLETE]")
        mock_extract.return_value = {
            "race_goal": "Bangalore Marathon",
            "race_date": "2026-10-15",
            "weekly_days": 4,
            "injuries": "None",
            "fitness_level": "Intermediate",
        }
        await handle_onboarding("+919876543210", "about 30km a week")

    call_kwargs = mock_sheets.create_runner.call_args[0][0]
    assert call_kwargs["name"] == "Arjun Singh"
    assert call_kwargs["phone"] == "+919876543210"
    assert call_kwargs["coach_id"] == "COACH_A"
    assert call_kwargs["race_goal"] == "Bangalore Marathon"
    assert call_kwargs["onboarded"] is True


@pytest.mark.asyncio
async def test_existing_runner_updated_not_created(runner, mock_sheets):
    """If runner_id is set (Razorpay flow), update existing row — don't create duplicate."""
    start_onboarding("+919876543210", "COACH_A", name="Priya", runner_id="RUN_TEST01")
    with patch("agents.onboarding_agent.llm") as mock_llm, \
         patch("agents.onboarding_agent.sheets", mock_sheets), \
         patch("agents.onboarding_agent._extract_profile", new_callable=AsyncMock) as mock_extract:
        mock_llm.complete = AsyncMock(return_value="All good! [COMPLETE]")
        mock_extract.return_value = {
            "race_goal": "Half Marathon",
            "race_date": "2026-01-19",
            "weekly_days": 4,
            "injuries": "None",
            "fitness_level": "Intermediate",
        }
        await handle_onboarding("+919876543210", "30km per week")

    mock_sheets.update_runner.assert_called_once()
    mock_sheets.create_runner.assert_not_called()


@pytest.mark.asyncio
async def test_session_stays_open_if_profile_incomplete():
    """If < 5 user messages, completion check should not fire."""
    start_onboarding("+919876543210", "COACH_A", name="Arjun")
    with patch("agents.onboarding_agent.llm") as mock_llm, \
         patch("agents.onboarding_agent._is_profile_complete", new_callable=AsyncMock) as mock_check:
        mock_llm.complete = AsyncMock(return_value="Any injuries?")
        mock_check.return_value = False
        await handle_onboarding("+919876543210", "hi")

    assert is_onboarding("+919876543210")
    mock_check.assert_not_called()  # shouldn't check with fewer than 5 user messages
