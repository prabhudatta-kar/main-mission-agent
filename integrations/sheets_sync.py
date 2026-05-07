import json
import logging
import os
import uuid
from datetime import date, datetime

import gspread
import pytz
from google.oauth2.service_account import Credentials

from config.settings import GOOGLE_SHEETS_CREDENTIALS_JSON, GOOGLE_SHEETS_WORKBOOK_ID

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
logger = logging.getLogger(__name__)


class SheetsClient:
    def __init__(self):
        self._client = None
        self._workbook = None

    def _connect(self):
        if self._workbook is not None:
            return
        creds_value = GOOGLE_SHEETS_CREDENTIALS_JSON or ""
        logger.info(f"Sheets creds: length={len(creds_value)}, first_50={repr(creds_value[:50])}")
        if os.path.isfile(creds_value):
            creds = Credentials.from_service_account_file(creds_value, scopes=SCOPES)
        else:
            try:
                creds_dict = json.loads(creds_value)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"GOOGLE_SHEETS_CREDENTIALS_JSON is not valid JSON (len={len(creds_value)}, "
                    f"starts={repr(creds_value[:80])}). "
                    "In Railway → Variables, paste the full contents of your service account JSON file."
                ) from e
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        self._client = gspread.authorize(creds)
        self._workbook = self._client.open_by_key(GOOGLE_SHEETS_WORKBOOK_ID)
        logger.info("Connected to Google Sheets workbook")

    def _tab(self, name: str):
        self._connect()
        return self._workbook.worksheet(name)

    def _rows(self, tab_name: str) -> list:
        return self._tab(tab_name).get_all_records()

    # --- Runners ---

    def get_runner(self, runner_id: str) -> dict:
        return next((r for r in self._rows("Runners") if r["runner_id"] == runner_id), None)

    def find_runner_by_phone(self, phone: str) -> dict:
        needle = _normalize_phone(phone)
        return next(
            (r for r in self._rows("Runners")
             if _normalize_phone(r["phone"]) == needle and r["status"] == "Active"),
            None,
        )

    def find_any_runner_by_phone(self, phone: str) -> dict:
        """Find runner by phone regardless of status — used to detect already-onboarded runners."""
        needle = _normalize_phone(phone)
        return next(
            (r for r in self._rows("Runners") if _normalize_phone(r["phone"]) == needle),
            None,
        )

    def get_all_active_runners(self) -> list:
        return [r for r in self._rows("Runners") if r["status"] == "Active"]

    def get_coach_runners(self, coach_id: str) -> list:
        return [
            r for r in self._rows("Runners")
            if r["coach_id"] == coach_id and r["status"] == "Active"
        ]

    def create_runner(self, data: dict) -> str:
        runner_id = f"RUN_{str(uuid.uuid4())[:6].upper()}"
        onboarded = "TRUE" if data.get("onboarded") else "FALSE"
        self._tab("Runners").append_row([
            runner_id,
            data.get("name", ""),
            data.get("phone", ""),
            data.get("coach_id", ""),
            data.get("race_goal", ""),
            data.get("race_date", ""),
            data.get("weekly_days", ""),
            data.get("injuries", ""),
            data.get("fitness_level", ""),
            data.get("start_date", ""),
            data.get("status", "Active"),
            "v1",
            data.get("payment_status", "Paid"),
            data.get("monthly_fee", ""),
            onboarded,
            data.get("notes", ""),
        ])
        logger.info(f"Created runner {runner_id} — {data.get('name')}")
        return runner_id

    def update_runner(self, runner_id: str, fields: dict):
        ws = self._tab("Runners")
        rows = ws.get_all_records()
        for i, row in enumerate(rows, start=2):
            if row["runner_id"] == runner_id:
                headers = list(row.keys())
                for field, value in fields.items():
                    if field in headers:
                        ws.update_cell(i, headers.index(field) + 1, str(value))
                logger.info(f"Updated runner {runner_id}: {list(fields.keys())}")
                break

    # --- Training Plans ---

    def get_todays_plan(self, runner_id: str) -> dict:
        today = date.today().isoformat()
        return next(
            (r for r in self._rows("Training_Plans") if r["runner_id"] == runner_id and r["date"] == today),
            None,
        )

    def get_all_todays_plans(self) -> dict:
        """Load Training_Plans tab once → {runner_id: plan} for today. Use in dashboard to avoid N calls."""
        today = date.today().isoformat()
        result = {}
        for r in self._rows("Training_Plans"):
            if r["date"] == today:
                result[r["runner_id"]] = r
        return result

    def get_all_recent_messages(self, n: int = 3) -> dict:
        """Load Conversation_Log tab once → {runner_id: [last n messages]}. Use in dashboard."""
        all_msgs: dict = {}
        for m in self._rows("Conversation_Log"):
            rid = m.get("runner_id", "")
            all_msgs.setdefault(rid, []).append(m)
        return {rid: msgs[-n:] for rid, msgs in all_msgs.items()}

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
        todays = [
            r for r in self._rows("Training_Plans")
            if r["date"] == today and r["runner_id"] in runner_ids
        ]
        return {
            "total": len(todays),
            "completed": sum(1 for r in todays if r.get("completed") == "TRUE"),
            "flagged": [r for r in todays if r.get("flags")],
        }

    # --- Coach Configs ---

    def get_coach_config(self, coach_id: str) -> dict:
        config = next(
            (r for r in self._rows("Coach_Configs") if r["coach_id"] == coach_id), None
        )
        if config:
            version = config.get("active_prompt_version", "v1")
            config["active_system_prompt"] = config.get(f"system_prompt_{version}", "")
        return config

    def find_coach_by_phone(self, phone: str) -> dict:
        return next(
            (r for r in self._rows("Coach_Configs") if r["coach_phone"] == phone and r["status"] == "Active"),
            None,
        )

    def get_all_active_coaches(self) -> list:
        return [r for r in self._rows("Coach_Configs") if r["status"] == "Active"]

    # --- Rules & Corrections ---

    def get_active_rules(self, coach_id: str) -> list:
        return [
            r for r in self._rows("Rules_And_Corrections")
            if r["coach_id"] == coach_id and r["status"] == "Active"
        ]

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
        self._tab("Platform_Log").append_row(
            [_now_ist(), event_type, runner_id, coach_id, details, status]
        )


def _now_ist() -> str:
    return datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_phone(phone: str) -> str:
    phone = str(phone).strip().replace(" ", "").replace("-", "").lstrip("0")
    if phone.startswith("+"):
        return phone
    if len(phone) == 10:          # bare 10-digit Indian mobile
        return "+91" + phone
    if len(phone) == 12 and phone.startswith("91"):
        return "+" + phone        # 919xxxxxxxxx → +919xxxxxxxxx
    return "+" + phone


sheets = SheetsClient()
