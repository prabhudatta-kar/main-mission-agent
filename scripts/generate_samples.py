"""
Shows every template filled with realistic sample data.

Run:
    python -m scripts.generate_samples

Use this to:
1. Review how each message will look before submitting to Wati
2. Spot templates that need wording changes
3. Copy the Wati-format body ({{1}}, {{2}}) for WhatsApp Business submission

No OpenAI or Google Sheets needed — all sample data is hardcoded.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from templates.catalog import TEMPLATES, fill_template

# ── Sample variable values per template ──────────────────────────────────────

SAMPLES = {
    "morning_run": {
        "first_name": "Priya",
        "session_type": "Tempo Run",
        "distance": "8",
        "intensity": "threshold",
        "weeks_to_race": "9",
        "race_goal": "Ladakh Marathon",
    },
    "morning_rest_day": {
        "first_name": "Arjun",
    },
    "evening_checkin_missed": {
        "first_name": "Sneha",
    },
    "weekly_summary": {
        "first_name": "Priya",
        "completed": "4",
        "total": "5",
        "total_km": "32",
        "race_goal": "Bangalore Marathon",
        "weeks_to_race": "7",
        "coach_note": "Great consistency this week. Long run on Sunday was excellent.",
    },
    "race_week": {
        "first_name": "Arjun",
        "race_goal": "Mumbai Half Marathon",
        "days_to_race": "5",
    },
    "feedback_solid": {
        "first_name": "Priya",
        "distance": "6",
        "session_type": "easy run",
        "observation": "Your zone 2 pace is getting stronger — noticeable improvement over last month.",
        "race_goal": "Ladakh Marathon",
    },
    "feedback_great": {
        "first_name": "Arjun",
        "distance": "21.1",
        "highlight": "negative split — second half faster than first. That's race execution right there",
        "race_goal": "Delhi Half Marathon",
    },
    "feedback_tough": {
        "first_name": "Sneha",
        "distance": "10",
    },
    "injury_response": {
        "first_name": "Priya",
        "body_part": "left knee",
    },
    "missed_first_time": {
        "first_name": "Arjun",
    },
    "missed_multiple": {
        "first_name": "Sneha",
    },
    "dropout_risk": {
        "first_name": "Priya",
    },
    "question_pacing": {
        "session_type": "easy run",
        "first_name": "Arjun",
        "target_pace": "6:30-7:00/km",
        "extra_note": "Don't look at your watch too much — go by feel.",
    },
    "question_general": {
        "first_name": "Sneha",
        "answer": "The best pre-run snack is something light and easy to digest — a banana or a few dates about 30-45 minutes before works well for most runners.",
    },
    "motivation_countdown": {
        "weeks_to_race": "3",
        "race_goal": "Bangalore Marathon",
        "first_name": "Priya",
    },
    "plan_update": {
        "first_name": "Arjun",
        "change_description": "your Sunday long run has been moved to Saturday this week",
        "reason": "Coach wants to give you an extra recovery day before your tempo on Monday.",
    },
    "escalation_notified": {
        "first_name": "Sneha",
    },
}

# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("MAIN MISSION — MESSAGE TEMPLATE PREVIEW")
    print("=" * 70)
    print()

    for tid, tmpl in TEMPLATES.items():
        print(f"{'─' * 70}")
        print(f"  TEMPLATE: {tid}")
        print(f"  WHEN:     {tmpl['scenario']}")
        print(f"  WATI:     {tmpl['wati_name']}")
        print()

        sample_vars = SAMPLES.get(tid, {})
        missing = [v for v in tmpl["variables"] if v not in sample_vars]
        if missing:
            print(f"  ⚠  Missing sample vars: {missing}")
            print()
            continue

        filled = fill_template(tid, sample_vars)
        print("  FILLED MESSAGE:")
        for line in filled.split("\n"):
            print(f"    {line}")
        print()
        print("  WATI SUBMISSION BODY:")
        for line in tmpl["wati_body"].split("\n"):
            print(f"    {line}")
        vars_indexed = list(enumerate(tmpl["variables"], start=1))
        print(f"  VARIABLE MAPPING: {', '.join(f'{{{{{{n}}}}}}={v}' for n, v in vars_indexed)}")
        print()

    print("=" * 70)
    print(f"Total templates: {len(TEMPLATES)}")
    print()
    print("Next steps:")
    print("  1. Review each filled message above")
    print("  2. Edit templates/catalog.py if wording needs adjusting")
    print("  3. Submit each WATI SUBMISSION BODY to Wati → Templates → New Template")
    print("  4. Wait for WhatsApp/Meta approval (~24 hours)")
    print("=" * 70)


if __name__ == "__main__":
    main()
