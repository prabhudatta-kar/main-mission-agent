"""
One-time setup script: creates all required tabs and header rows in the
MainMission Platform Google Sheets workbook.

Run once after creating the workbook and sharing it with your service account:
    python -m scripts.setup_sheets
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gspread
from google.oauth2.service_account import Credentials
from config.settings import GOOGLE_SHEETS_CREDENTIALS_JSON, GOOGLE_SHEETS_WORKBOOK_ID

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

TABS = {
    "Runners": [
        "runner_id", "name", "phone", "coach_id", "race_goal", "race_date",
        "weekly_days", "injuries", "fitness_level", "start_date", "status",
        "prompt_version", "payment_status", "monthly_fee", "onboarded", "notes",
    ],
    "Training_Plans": [
        "plan_id", "runner_id", "date", "day_type", "session_type", "distance_km",
        "duration_min", "intensity", "rpe_target", "coach_notes", "sent", "sent_at",
        "completed", "actual_distance", "rpe_actual", "runner_feedback", "flags",
    ],
    "Coach_Configs": [
        "coach_id", "coach_name", "coach_phone", "active_prompt_version",
        "system_prompt_v1", "system_prompt_v1_date",
        "system_prompt_v2", "system_prompt_v2_date",
        "system_prompt_v3", "system_prompt_v3_date",
        "coaching_style", "escalation_rules", "status",
    ],
    "Rules_And_Corrections": [
        "rule_id", "coach_id", "date_added", "situation", "wrong_response",
        "correct_response", "rule_derived", "status", "source",
    ],
    "Conversation_Log": [
        "log_id", "timestamp", "runner_id", "coach_id", "direction", "message",
        "message_type", "handled_by", "escalated", "escalation_reason",
    ],
    "Platform_Log": [
        "timestamp", "event_type", "runner_id", "coach_id", "details", "status",
    ],
}


def main():
    print(f"Connecting to workbook {GOOGLE_SHEETS_WORKBOOK_ID}...")
    creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_JSON, scopes=SCOPES)
    client = gspread.authorize(creds)
    workbook = client.open_by_key(GOOGLE_SHEETS_WORKBOOK_ID)

    existing_titles = {ws.title for ws in workbook.worksheets()}

    for tab_name, headers in TABS.items():
        if tab_name in existing_titles:
            ws = workbook.worksheet(tab_name)
            existing_headers = ws.row_values(1)
            if existing_headers == headers:
                print(f"  ✓ {tab_name} — already set up")
            else:
                print(f"  ! {tab_name} — exists but headers differ (not overwriting)")
        else:
            ws = workbook.add_worksheet(title=tab_name, rows=1000, cols=len(headers) + 2)
            ws.append_row(headers)
            print(f"  + {tab_name} — created with {len(headers)} columns")

    # Remove the default empty Sheet1 if it exists and we created everything else
    if "Sheet1" in existing_titles and len(existing_titles) == 1:
        try:
            workbook.del_worksheet(workbook.worksheet("Sheet1"))
            print("  - Removed default Sheet1")
        except Exception:
            pass

    print("\nSetup complete. All tabs ready.")


if __name__ == "__main__":
    main()
