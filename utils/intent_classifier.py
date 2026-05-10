INJURY_KEYWORDS  = {"pain", "hurt", "injury", "sore", "tight", "pulled", "swollen", "twisted", "ache", "strain"}
QUIT_KEYWORDS    = {"quit", "stop", "give up", "drop out", "dropping out", "can't do this", "cannot do this"}
MISSED_KEYWORDS  = {"missed", "skipped", "couldn't", "didn't run", "did not run", "could not run"}
FEEDBACK_KEYWORDS = {"done", "completed", "finished", "ran", "did it", "km", "minutes", "felt", "managed"}
RACE_ADD_PHRASES = [
    "signed up for", "registered for", "signing up for", "also running",
    "also doing", "want to add", "add a race", "new race", "another race",
    "entered for", "enrolled for",
]


def classify_intent(message: str) -> str:
    lower = message.lower()
    words = set(lower.split())

    if words & INJURY_KEYWORDS:
        return "injury_flag"
    if any(phrase in lower for phrase in QUIT_KEYWORDS):
        return "dropout_risk"
    if any(kw in lower for kw in MISSED_KEYWORDS):
        return "missed_session"
    if any(phrase in lower for phrase in RACE_ADD_PHRASES):
        return "race_update"
    if words & FEEDBACK_KEYWORDS:
        return "feedback"
    return "question"
