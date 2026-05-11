INJURY_KEYWORDS  = {"pain", "hurt", "hurts", "injury", "sore", "tight", "pulled", "swollen", "twisted", "ache", "strain"}
QUIT_KEYWORDS    = {"quit", "stop", "give up", "drop out", "dropping out", "can't do this", "cannot do this"}
MISSED_KEYWORDS  = {"missed", "skipped", "couldn't", "didn't run", "did not run", "could not run"}
FEEDBACK_KEYWORDS = {"done", "completed", "finished", "ran", "did it", "km", "minutes", "felt", "managed"}
RACE_ADD_PHRASES = [
    "signed up for", "registered for", "signing up for", "also running",
    "also doing", "want to add", "add a race", "new race", "another race",
    "entered for", "enrolled for",
]

PLAN_RESCHEDULE_PHRASES = [
    "reschedule", "move my", "move the", "postpone", "shift my", "push to",
    "swap my", "can i do it on", "move it to",
    "change my session", "different day",
]

PLAN_TWEAK_PHRASES = [
    "make it shorter", "make it longer", "make it easier", "make it harder",
    "can i reduce", "can i skip", "instead of", "change the distance",
    "shorten the", "adjust my", "tweak my", "modify my",
    "can i do less", "can i do more", "can i change",
]

PLAN_QUERY_PHRASES = [
    "what's my plan", "what is my plan", "show me my", "my plan for",
    "this week's training", "this week's plan", "training this week",
    "this weeks plan", "this weeks training",
    "tomorrow's session", "tomorrow's workout", "what am i running",
    "what should i do", "what's my workout", "what is my workout",
    "my workout", "what workout", "exact workout",
    "schedule for", "sessions this week", "plan for this week",
    "plan for tomorrow", "what's today's", "what is today's session",
    "what's the plan", "what is the plan", "internal session",
    "what am i doing", "today's session", "today's workout",
    # next session queries
    "next workout", "next run", "next session", "next training", "when is my next",
    "upcoming session", "upcoming run", "upcoming workout",
    # distance / detail follow-ups in context of a plan
    "what distance", "how far", "as per plan", "planned distance",
    "what's the distance", "what is the distance", "how many km",
    "give me details", "more details", "tell me more about",
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
    if any(phrase in lower for phrase in PLAN_RESCHEDULE_PHRASES):
        return "plan_reschedule"
    # "move [day/run/session]" — catches "move thursdays run to friday"
    if "move" in lower and any(w in lower for w in ("run", "session", "workout", "monday", "tuesday",
                                                     "wednesday", "thursday", "friday", "saturday", "sunday")):
        return "plan_reschedule"
    if any(phrase in lower for phrase in PLAN_TWEAK_PHRASES):
        return "plan_tweak"
    if any(phrase in lower for phrase in PLAN_QUERY_PHRASES):
        return "plan_query"
    if words & FEEDBACK_KEYWORDS:
        return "feedback"
    return "question"
