"""
Intent classification drives escalation and logging.
Any change to keywords must not break these contracts.
"""
import pytest
from utils.intent_classifier import classify_intent


@pytest.mark.parametrize("message", [
    "my knee is in pain today",
    "I hurt my ankle",
    "feeling sore after yesterday",
    "something feels tight in my calf",
    "I think I pulled a muscle",
    "my ankle is swollen",
    "twisted my knee on the trail",
])
def test_injury_flag(message):
    assert classify_intent(message) == "injury_flag"


@pytest.mark.parametrize("message", [
    "I want to quit this programme",
    "I think I need to stop",
    "I give up, can't do this anymore",
    "thinking of dropping out",
])
def test_dropout_risk(message):
    assert classify_intent(message) == "dropout_risk"


@pytest.mark.parametrize("message", [
    "missed my run today",
    "skipped the session",
    "I couldn't run this morning",
    "didn't run yesterday",
])
def test_missed_session(message):
    assert classify_intent(message) == "missed_session"


@pytest.mark.parametrize("message", [
    "done! ran 6km today",
    "completed the tempo run",
    "finished my long run, felt great",
    "managed 8km at zone 2",
    "ran for 45 minutes",
])
def test_feedback(message):
    assert classify_intent(message) == "feedback"


@pytest.mark.parametrize("message", [
    "what pace should I run at?",
    "how do I fuel for a long run?",
    "hi",
    "good morning",
    "when is rest day?",
])
def test_question(message):
    assert classify_intent(message) == "question"


def test_injury_takes_priority_over_feedback():
    """'Ran but knee pain' should be injury_flag, not feedback."""
    assert classify_intent("ran 5km but knee pain the whole way") == "injury_flag"
