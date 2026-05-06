"""
Escalation must fire for injury and dropout risk — never silently drop these.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from utils.escalation import should_escalate


def test_escalates_on_injury(runner):
    assert should_escalate("injury_flag", "knee pain", runner) is True


def test_escalates_on_dropout(runner):
    assert should_escalate("dropout_risk", "I want to quit", runner) is True


def test_no_escalation_on_feedback(runner):
    assert should_escalate("feedback", "ran 6km today", runner) is False


def test_no_escalation_on_question(runner):
    assert should_escalate("question", "what pace should I run?", runner) is False


def test_no_escalation_on_missed_session(runner):
    assert should_escalate("missed_session", "skipped today", runner) is False


@pytest.mark.asyncio
async def test_notify_coach_sends_whatsapp(runner, coach, mock_sheets, mock_whatsapp):
    with patch("utils.escalation.sheets", mock_sheets), \
         patch("utils.escalation.whatsapp", mock_whatsapp):
        mock_sheets.get_coach_config.return_value = coach
        from utils.escalation import notify_coach
        await notify_coach("COACH_A", runner, "knee is really hurting", reason="injury_flag")

    mock_whatsapp.send_text.assert_called_once()
    call_args = mock_whatsapp.send_text.call_args
    assert coach["coach_phone"] in call_args[0]
    assert "Priya Sharma" in call_args[0][1]
    assert "injury_flag" in call_args[0][1]
