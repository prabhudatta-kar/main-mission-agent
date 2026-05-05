INJURY_KEYWORDS = {"pain", "hurt", "injury", "sore", "tight", "pulled", "swollen", "twisted", "ache", "strain"}
QUIT_KEYWORDS = {"quit", "stop", "give up", "drop out", "can't do this", "cannot"}
MISSED_KEYWORDS = {"missed", "skipped", "couldn't", "didn't run", "did not run"}
FEEDBACK_KEYWORDS = {"done", "completed", "finished", "ran", "did it", "km", "minutes", "felt", "managed"}


def classify_intent(message: str) -> str:
    lower = message.lower()
    words = set(lower.split())

    if words & INJURY_KEYWORDS:
        return "injury_flag"
    if any(phrase in lower for phrase in QUIT_KEYWORDS):
        return "dropout_risk"
    if words & MISSED_KEYWORDS:
        return "missed_session"
    if words & FEEDBACK_KEYWORDS:
        return "feedback"
    return "question"
