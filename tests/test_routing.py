"""
Routing is the most critical requirement:
- Onboarded runner → runner agent (NEVER re-onboard)
- Unboarded runner → onboarding
- Unknown phone (not in sheet) → onboarding or unknown
- Coach phone → coach agent

These tests use mocked Sheets and LLM so no external services are needed.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from agents.master_agent import compute_response, identify_sender


# ── identify_sender ──────────────────────────────────────────────────────────

def test_identify_active_runner(runner, mock_sheets):
    with patch("agents.master_agent.sheets", mock_sheets):
        mock_sheets.find_any_runner_by_phone.return_value = runner
        result = identify_sender("+919876543210")
    assert result["type"] == "runner"
    assert result["id"] == "RUN_TEST01"


def test_identify_coach(coach, mock_sheets):
    with patch("agents.master_agent.sheets", mock_sheets):
        mock_sheets.find_any_runner_by_phone.return_value = None
        mock_sheets.find_coach_by_phone.return_value = coach
        result = identify_sender("+919999999999")
    assert result["type"] == "coach"
    assert result["id"] == "COACH_A"


def test_identify_unknown(mock_sheets):
    with patch("agents.master_agent.sheets", mock_sheets):
        mock_sheets.find_any_runner_by_phone.return_value = None
        mock_sheets.find_coach_by_phone.return_value = None
        result = identify_sender("+910000000000")
    assert result["type"] == "unknown"


def test_identify_uses_any_runner_not_just_active(runner, mock_sheets):
    """Paused or completed runners must still be identified — not treated as unknown."""
    paused = {**runner, "status": "Paused"}
    with patch("agents.master_agent.sheets", mock_sheets):
        mock_sheets.find_any_runner_by_phone.return_value = paused
        result = identify_sender("+919876543210")
    assert result["type"] == "runner"


# ── compute_response routing ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_onboarded_runner_goes_to_runner_agent(runner, mock_sheets):
    with patch("agents.master_agent.sheets", mock_sheets), \
         patch("agents.master_agent.generate_runner_response", new_callable=AsyncMock) as mock_gen:
        mock_sheets.find_any_runner_by_phone.return_value = runner
        mock_gen.return_value = {"response": "Hey Priya!", "intent": "question"}

        result = await compute_response("+919876543210", "hi")

    assert result["sender_type"] == "runner"
    assert result["response"] == "Hey Priya!"
    mock_gen.assert_called_once()


@pytest.mark.asyncio
async def test_onboarded_runner_never_sees_onboarding(runner, mock_sheets):
    """Core requirement: a runner with onboarded=TRUE must never be asked to onboard."""
    with patch("agents.master_agent.sheets", mock_sheets), \
         patch("agents.master_agent.generate_runner_response", new_callable=AsyncMock) as mock_gen, \
         patch("agents.master_agent.handle_onboarding", new_callable=AsyncMock) as mock_onboard:
        mock_sheets.find_any_runner_by_phone.return_value = runner
        mock_gen.return_value = {"response": "Hey!", "intent": "question"}

        await compute_response("+919876543210", "hi")

    mock_onboard.assert_not_called()


@pytest.mark.asyncio
async def test_unboarded_runner_goes_to_onboarding(unboarded_runner, mock_sheets):
    with patch("agents.master_agent.sheets", mock_sheets), \
         patch("agents.master_agent.is_onboarding", return_value=False), \
         patch("agents.master_agent.start_onboarding"), \
         patch("agents.master_agent.handle_onboarding", new_callable=AsyncMock) as mock_onboard:
        mock_sheets.find_any_runner_by_phone.return_value = unboarded_runner
        mock_onboard.return_value = "What race are you training for?"

        result = await compute_response("+919876543210", "hi")

    assert result["sender_type"] == "onboarding"
    mock_onboard.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_phone_with_no_coach_returns_unknown(mock_sheets):
    with patch("agents.master_agent.sheets", mock_sheets):
        mock_sheets.find_any_runner_by_phone.return_value = None
        mock_sheets.find_coach_by_phone.return_value = None

        result = await compute_response("+910000000000", "hi", coach_id=None)

    assert result["sender_type"] == "unknown"
    assert "panel" in result["response"].lower() or "coach" in result["response"].lower()


@pytest.mark.asyncio
async def test_unknown_phone_with_coach_starts_onboarding(mock_sheets):
    with patch("agents.master_agent.sheets", mock_sheets), \
         patch("agents.master_agent.is_onboarding", return_value=False), \
         patch("agents.master_agent.start_onboarding") as mock_start, \
         patch("agents.master_agent.handle_onboarding", new_callable=AsyncMock) as mock_onboard:
        mock_sheets.find_any_runner_by_phone.return_value = None
        mock_sheets.find_coach_by_phone.return_value = None
        mock_onboard.return_value = "Welcome! What race are you training for?"

        result = await compute_response("+910000000000", "hi", coach_id="COACH_A", name="Arjun")

    assert result["sender_type"] == "onboarding"
    mock_start.assert_called_once()


@pytest.mark.asyncio
async def test_coach_identified_correctly(coach, mock_sheets):
    """compute_response returns sender_type=coach for coach phone numbers."""
    with patch("agents.master_agent.sheets", mock_sheets):
        mock_sheets.find_any_runner_by_phone.return_value = None
        mock_sheets.find_coach_by_phone.return_value = coach

        result = await compute_response("+919999999999", "tell everyone rest day tomorrow")

    assert result["sender_type"] == "coach"


@pytest.mark.asyncio
async def test_handle_incoming_calls_coach_handler(coach, mock_sheets, mock_whatsapp):
    """The real webhook (handle_incoming) must call handle_coach_message for coaches."""
    from agents.master_agent import handle_incoming
    with patch("agents.master_agent.sheets", mock_sheets), \
         patch("agents.master_agent.whatsapp", mock_whatsapp), \
         patch("agents.master_agent.handle_coach_message", new_callable=AsyncMock) as mock_coach:
        mock_sheets.find_any_runner_by_phone.return_value = None
        mock_sheets.find_coach_by_phone.return_value = coach
        mock_coach.return_value = None

        await handle_incoming({"waId": "919999999999", "text": {"body": "tell everyone rest day"}, "type": "text"})

    mock_coach.assert_called_once()


@pytest.mark.asyncio
async def test_bare_10_digit_phone_resolves_as_runner(runner, mock_sheets):
    """Phone without country code must still find the runner."""
    with patch("agents.master_agent.sheets", mock_sheets), \
         patch("agents.master_agent.generate_runner_response", new_callable=AsyncMock) as mock_gen:
        mock_sheets.find_any_runner_by_phone.return_value = runner
        mock_gen.return_value = {"response": "Hi!", "intent": "question"}

        result = await compute_response("9876543210", "hi")  # no +91

    assert result["sender_type"] == "runner"


@pytest.mark.asyncio
async def test_onboarding_continues_if_session_exists(unboarded_runner, mock_sheets):
    """If mid-onboarding session exists, don't restart — continue it."""
    with patch("agents.master_agent.sheets", mock_sheets), \
         patch("agents.master_agent.is_onboarding", return_value=True), \
         patch("agents.master_agent.start_onboarding") as mock_start, \
         patch("agents.master_agent.handle_onboarding", new_callable=AsyncMock) as mock_onboard:
        mock_sheets.find_any_runner_by_phone.return_value = unboarded_runner
        mock_onboard.return_value = "How many days can you train?"

        await compute_response("+919876543210", "Ladakh Marathon, September")

    mock_start.assert_not_called()
    mock_onboard.assert_called_once()
