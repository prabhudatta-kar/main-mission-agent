import uuid
from datetime import date, datetime
import gspread
import pytz
from google.oauth2.service_account import Credentials
from config.settings import GOOGLE_SHEETS_CREDENTIALS_JSON, GOOGLE_SHEETS_WORKBOOK_ID

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClient:
    def __init__(self):
        creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_JSON, scopes=SCOPES)
        self._client = gspread.authorize(creds)
        self._workbook = self._client.open_by_key(GOOGLE_SHEETS_WORKBOOK_ID)

    def _tab(self, name: str):
        return self._workbook.worksheet(name)

    def _rows(self, tab_name: str) -> list:
        return self._tab(tab_name).get_all_records()

    # --- Runners ---

    def get_runner(self, runner_id: str) -> dict:
        return next((r for r in self._rows("Runners") if r["runner_id"] == runner_id), None)

    def find_runner_by_phone(self, phone: str) -> dict:
        return next((r for r in self._rows("Runners") if r["phone"] == phone and r["status"] == "Active"), None)

    def get_all_active_runners(self) -> list:
        return [r for r in self._rows("Runners") if r["status"] == "Active"]

    def get_coach_runners(self, coach_id: str) -> list:
        return [r for r in self._rows("Runners") if r["coach_id"] == coach_id and r["status"] == "Active"]

    def create_runner(self, data: dict) -> str:
        runner_id = f"RUN_{str(uuid.uuid4())[:6].upper()}"
        self._tab("Runners").append_row([
            runner_id, data.get("name"), data.get("phone"), data.get("coach_id"),
            "", "", data.get("weekly_days", ""), "", "", data.get("start_date", ""),
            data.get("status", "Active"), "v1", data.get("payment_status", "Paid"),
            data.get("monthly_fee", ""), "FALSE", ""
        ])
        return runner_id

    # --- Training Plans ---

    def get_todays_plan(self, runner_id: str) -> dict:
        today = date.today().isoformat()
        return next((r for r in self._rows("Training_Plans") if r["runner_id"] == runner_id and r["date"] == today), None)

    def mark_plan_sent(self, plan_id: str):
        ws = self._tab("Training_Plans")
        rows = ws.get_all_records()
        for i, row in enumerate(rows, start=2):
            if row["plan_id"] == plan_id:
                headers = list(row.keys())
                ws.update_cell(i, headers.index("sent") + 1, "TRUE")
                ws.update_cell(i, headers.index("sent_at") + 1, _now_ist())
                break

    def update_plan_feedback(self, runner_id: str, message: str):
        today = date.today().isoformat()
        ws = self._tab("Training_Plans")
        rows = ws.get_all_records()
        for i, row in enumerate(rows, start=2):
            if row["runner_id"] == runner_id and row["date"] == today:
                ws.update_cell(i, list(row.keys()).index("runner_feedback") + 1, message)
                break

    def get_runners_with_no_feedback_today(self) -> list:
        today = date.today().isoformat()
        no_feedback_ids = {
            r["runner_id"] for r in self._rows("Training_Plans")
            if r["date"] == today and not r.get("runner_feedback") and r.get("sent") == "TRUE"
        }
        return [r for r in self._rows("Runners") if r["runner_id"] in no_feedback_ids]

    def get_todays_summary(self, coach_id: str) -> dict:
        today = date.today().isoformat()
        runner_ids = {r["runner_id"] for r in self.get_coach_runners(coach_id)}
        todays = [r for r in self._rows("Training_Plans") if r["date"] == today and r["runner_id"] in runner_ids]
        return {
            "total": len(todays),
            "completed": sum(1 for r in todays if r.get("completed") == "TRUE"),
            "flagged": [r for r in todays if r.get("flags")]
        }

    # --- Coach Configs ---

    def get_coach_config(self, coach_id: str) -> dict:
        config = next((r for r in self._rows("Coach_Configs") if r["coach_id"] == coach_id), None)
        if config:
            version = config.get("active_prompt_version", "v1")
            config["active_system_prompt"] = config.get(f"system_prompt_{version}", "")
        return config

    def find_coach_by_phone(self, phone: str) -> dict:
        return next((r for r in self._rows("Coach_Configs") if r["coach_phone"] == phone and r["status"] == "Active"), None)

    def get_all_active_coaches(self) -> list:
        return [r for r in self._rows("Coach_Configs") if r["status"] == "Active"]

    # --- Rules & Corrections ---

    def get_active_rules(self, coach_id: str) -> list:
        return [r for r in self._rows("Rules_And_Corrections") if r["coach_id"] == coach_id and r["status"] == "Active"]

    def add_rule(self, coach_id: str, rule: str, source: str, raw_message: str = ""):
        rule_id = f"RULE_{str(uuid.uuid4())[:6].upper()}"
        self._tab("Rules_And_Corrections").append_row(
            [rule_id, coach_id, date.today().isoformat(), raw_message, "", "", rule, "Active", source]
        )

    # --- Conversation Log ---

    def get_last_n_messages(self, runner_id: str, n: int = 5) -> list:
        msgs = [r for r in self._rows("Conversation_Log") if r["runner_id"] == runner_id]
        return msgs[-n:]

    def log_conversation(self, runner_id: str, coach_id: str, inbound: str, outbound: str, intent: str):
        ws = self._tab("Conversation_Log")
        ts = _now_ist()
        base_id = f"LOG_{str(uuid.uuid4())[:6].upper()}"
        ws.append_row([base_id, ts, runner_id, coach_id, "inbound", inbound, intent, "agent", "FALSE", ""])
        ws.append_row([base_id + "_r", ts, runner_id, coach_id, "outbound", outbound, intent, "agent", "FALSE", ""])

    # --- Platform Log ---

    def log_platform_event(self, event_type: str, runner_id: str, coach_id: str, details: str, status: str = "success"):
        self._tab("Platform_Log").append_row([_now_ist(), event_type, runner_id, coach_id, details, status])


def _now_ist() -> str:
    return datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")


sheets = SheetsClient()
