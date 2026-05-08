"""
Template catalog for all agent-to-runner messages.

Each template has:
  - id: unique key
  - scenario: when to use it (shown to LLM for selection)
  - body: message text with {variable} placeholders
  - variables: list of required variable names
  - wati_name: the template name to register in Wati (snake_case, 60 char max)
  - wati_body: WhatsApp-submission format using {{1}}, {{2}} positional slots

To add a new template: add an entry to TEMPLATES, then run
  python -m scripts.generate_samples
to preview filled examples before submitting to Wati.
"""

TEMPLATES: dict[str, dict] = {

    # ── Proactive (business-initiated) ─────────────────────────────────────

    "onboarding_welcome": {
        "scenario": "New runner just paid — send first WhatsApp message to start onboarding",
        "body":      "Welcome to Main Mission, {runner_name}! 🏃 I'm your AI coaching assistant. Your coach {coach_name} has set up your programme. Reply HI to get started — I'll ask you a few quick questions to personalise your plan.",
        "variables": ["runner_name", "coach_name"],
        "wati_name": "onboarding_welcome",
        "wati_body": "Welcome to Main Mission, {{1}}! 🏃 I'm your AI coaching assistant. Your coach {{2}} has set up your programme. Reply HI to get started — I'll ask you a few quick questions to personalise your plan.",
    },

    "morning_run": {
        "scenario": "Runner has a run session today — send morning workout nudge",
        "body": "Morning {first_name}! Today's session: {session_type} — {distance}km at {intensity} pace. {weeks_to_race} weeks to {race_goal}. Reply GO for full details 🏃",
        "variables": ["first_name", "session_type", "distance", "intensity", "weeks_to_race", "race_goal"],
        "wati_name": "mm_morning_run",
        "wati_body": "Morning {{1}}! Today's session: {{2}} — {{3}}km at {{4}} pace. {{5}} weeks to {{6}}. Reply GO for full details 🏃",
    },

    "morning_rest_day": {
        "scenario": "Today is a scheduled rest day for the runner",
        "body": "Rest day today, {first_name}! You've put in the hard work this week — recovery is where the fitness actually builds. Reply READY if you're set for tomorrow 💪",
        "variables": ["first_name"],
        "wati_name": "mm_morning_rest_day",
        "wati_body": "Rest day today, {{1}}! You've put in the hard work this week — recovery is where the fitness actually builds. Reply READY if you're set for tomorrow 💪",
    },

    "evening_checkin_missed": {
        "scenario": "Runner hasn't responded or logged their session by evening",
        "body": "Hey {first_name}, missed you on the roads today! Rest day or life happened? Just reply and let me know 🙂",
        "variables": ["first_name"],
        "wati_name": "mm_evening_checkin",
        "wati_body": "Hey {{1}}, missed you on the roads today! Rest day or life happened? Just reply and let me know 🙂",
    },

    "weekly_summary": {
        "scenario": "Weekly summary for the runner — sent every Sunday evening",
        "body": "{first_name}, here's your week:\n✅ Sessions: {completed}/{total}\n📏 Distance: {total_km}km\n🗓 Weeks to {race_goal}: {weeks_to_race}\n\n{coach_note}",
        "variables": ["first_name", "completed", "total", "total_km", "race_goal", "weeks_to_race", "coach_note"],
        "wati_name": "mm_weekly_summary",
        "wati_body": "{{1}}, here's your week:\n✅ Sessions: {{2}}/{{3}}\n📏 Distance: {{4}}km\n🗓 Weeks to {{5}}: {{6}}\n\n{{7}}",
    },

    "race_week": {
        "scenario": "It is race week (7 days or fewer to race day)",
        "body": "Race week, {first_name}! 🎉 {race_goal} is {days_to_race} days away. This week is about staying sharp — light sessions, good sleep, trust your training. You've earned this.",
        "variables": ["first_name", "race_goal", "days_to_race"],
        "wati_name": "mm_race_week",
        "wati_body": "Race week, {{1}}! 🎉 {{2}} is {{3}} days away. This week is about staying sharp — light sessions, good sleep, trust your training. You've earned this.",
    },

    # ── Conversational responses (within 24h session window) ────────────────

    "feedback_solid": {
        "scenario": "Runner completed their session and shared feedback — solid effort",
        "body": "Solid work, {first_name}! {distance}km of {session_type} done. {observation} Keep stacking these sessions and {race_goal} will take care of itself 🏃",
        "variables": ["first_name", "distance", "session_type", "observation", "race_goal"],
        "wati_name": "mm_feedback_solid",
        "wati_body": "Solid work, {{1}}! {{2}}km of {{3}} done. {{4}} Keep stacking these sessions and {{5}} will take care of itself 🏃",
    },

    "feedback_great": {
        "scenario": "Runner had an exceptional session — significantly above target or personal best",
        "body": "That's a big one, {first_name}! {distance}km — {highlight}. Your {race_goal} is going to feel so much easier for sessions like this 🔥",
        "variables": ["first_name", "distance", "highlight", "race_goal"],
        "wati_name": "mm_feedback_great",
        "wati_body": "That's a big one, {{1}}! {{2}}km — {{3}}. Your {{4}} is going to feel so much easier for sessions like this 🔥",
    },

    "feedback_tough": {
        "scenario": "Runner completed the session but it was hard — high RPE, slow pace, or struggled",
        "body": "Getting it done on a tough day is what separates finishers from everyone else, {first_name}. {distance}km when it felt hard counts double 💪",
        "variables": ["first_name", "distance"],
        "wati_name": "mm_feedback_tough",
        "wati_body": "Getting it done on a tough day is what separates finishers from everyone else, {{1}}. {{2}}km when it felt hard counts double 💪",
    },

    "injury_response": {
        "scenario": "Runner mentions pain, injury, soreness, or physical discomfort",
        "body": "Thanks for telling me, {first_name}. Please don't run today — rest and let that {body_part} settle. I've flagged this to your coach and they'll advise. Never push through pain 🙏",
        "variables": ["first_name", "body_part"],
        "wati_name": "mm_injury_response",
        "wati_body": "Thanks for telling me, {{1}}. Please don't run today — rest and let that {{2}} settle. I've flagged this to your coach and they'll advise. Never push through pain 🙏",
    },

    "missed_first_time": {
        "scenario": "Runner missed one session — first or second miss, tone should be light",
        "body": "No worries, {first_name}! Life happens. We'll pick it back up tomorrow — rest is sometimes exactly what the body needs anyway.",
        "variables": ["first_name"],
        "wati_name": "mm_missed_first_time",
        "wati_body": "No worries, {{1}}! Life happens. We'll pick it back up tomorrow — rest is sometimes exactly what the body needs anyway.",
    },

    "missed_multiple": {
        "scenario": "Runner has missed 3 or more consecutive sessions",
        "body": "Hey {first_name}, I've noticed you've missed the last few sessions. That's completely okay — life gets in the way. Just want to check in: is everything alright? Your coach can adjust the plan if you need it 💙",
        "variables": ["first_name"],
        "wati_name": "mm_missed_multiple",
        "wati_body": "Hey {{1}}, I've noticed you've missed the last few sessions. That's completely okay — life gets in the way. Just want to check in: is everything alright? Your coach can adjust the plan if you need it 💙",
    },

    "dropout_risk": {
        "scenario": "Runner expresses desire to quit, extreme frustration, or mentions stopping the programme",
        "body": "{first_name}, I hear you — training gets really hard sometimes. I've let your coach know. They'll reach out personally. You don't have to figure this out alone 🙏",
        "variables": ["first_name"],
        "wati_name": "mm_dropout_support",
        "wati_body": "{{1}}, I hear you — training gets really hard sometimes. I've let your coach know. They'll reach out personally. You don't have to figure this out alone 🙏",
    },

    "question_pacing": {
        "scenario": "Runner asks about pace, speed, or how fast to run",
        "body": "For your {session_type} today, {first_name}, aim for {target_pace} — you should be able to hold a full conversation. If you're gasping, slow down. {extra_note}",
        "variables": ["session_type", "first_name", "target_pace", "extra_note"],
        "wati_name": "mm_question_pacing",
        "wati_body": "For your {{1}} today, {{2}}, aim for {{3}} — you should be able to hold a full conversation. If you're gasping, slow down. {{4}}",
    },

    "question_general": {
        "scenario": "Runner asks a general running, training, or race question not covered by other templates",
        "body": "{first_name}, {answer}",
        "variables": ["first_name", "answer"],
        "wati_name": "mm_question_general",
        "wati_body": "{{1}}, {{2}}",
    },

    "motivation_countdown": {
        "scenario": "Runner needs motivation — specifically when 4 weeks or fewer from race day",
        "body": "{weeks_to_race} weeks to {race_goal}, {first_name}. Every session you complete now is a brick in your foundation. The runners who show up on hard days are the ones who cross the finish line smiling 🏁",
        "variables": ["weeks_to_race", "race_goal", "first_name"],
        "wati_name": "mm_motivation_countdown",
        "wati_body": "{{1}} weeks to {{2}}, {{3}}. Every session you complete now is a brick in your foundation. The runners who show up on hard days are the ones who cross the finish line smiling 🏁",
    },

    "plan_update": {
        "scenario": "Informing runner about a change to their training plan",
        "body": "Quick update, {first_name} — {change_description}. {reason} Any questions, just reply here.",
        "variables": ["first_name", "change_description", "reason"],
        "wati_name": "mm_plan_update",
        "wati_body": "Quick update, {{1}} — {{2}}. {{3}} Any questions, just reply here.",
    },

    "escalation_notified": {
        "scenario": "Confirming to runner that their concern has been passed to the coach",
        "body": "I've passed this on to your coach, {first_name}. They'll get back to you soon. In the meantime, take it easy 🙏",
        "variables": ["first_name"],
        "wati_name": "mm_escalation_notified",
        "wati_body": "I've passed this on to your coach, {{1}}. They'll get back to you soon. In the meantime, take it easy 🙏",
    },
}


def get_template(template_id: str):
    return TEMPLATES.get(template_id)


def fill_template(template_id: str, variables: dict) -> str:
    """Fill a template with variables. Returns the filled message string."""
    tmpl = TEMPLATES.get(template_id)
    if not tmpl:
        raise ValueError(f"Unknown template: {template_id}")
    try:
        return tmpl["body"].format(**variables)
    except KeyError as e:
        raise ValueError(f"Missing variable {e} for template '{template_id}'")


def template_menu() -> str:
    """Summary of all templates for injection into the LLM selection prompt."""
    lines = []
    for tid, tmpl in TEMPLATES.items():
        vars_list = ", ".join(tmpl["variables"])
        lines.append(f'- "{tid}": {tmpl["scenario"]} | vars: {vars_list}')
    return "\n".join(lines)
