"""
Primary database layer — Firebase Firestore.

Collections:
  runners           — runner profiles
  training_plans    — per-runner per-day sessions
  coaches           — coach configs + system prompts
  rules             — coach corrections and rules
  conversations     — all messages in/out
  platform_events   — payments, onboarding, errors

Firestore is queried directly (no full-table scans like Sheets).
For Sheets sync (coach view), see integrations/sheets_sync.py.
"""

import json
import logging
import os
import random
import string
import uuid


def _make_id(prefix: str, length: int = 10) -> str:
    """Generate a prefixed alphanumeric ID, e.g. B3F9K2X1M7 for runners."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=length - 1))
    return prefix + suffix
from datetime import date, datetime

import firebase_admin
import pytz
from firebase_admin import credentials, firestore

from config.settings import FIREBASE_CREDENTIALS_JSON, FIREBASE_PROJECT_ID
from utils.helpers import normalize_phone

logger = logging.getLogger(__name__)


def _now_ist() -> str:
    return datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")


def _doc(doc) -> dict:
    if not doc.exists:
        return None
    d = doc.to_dict()
    d.setdefault("_id", doc.id)
    return d


class FirebaseClient:
    def __init__(self):
        self._db = None

    def _connect(self):
        if self._db is not None:
            return
        if not firebase_admin._apps:
            cred_value = FIREBASE_CREDENTIALS_JSON or ""
            logger.info(f"Firebase creds: len={len(cred_value)}, starts={repr(cred_value[:30])}")
            if os.path.isfile(cred_value):
                cred = credentials.Certificate(cred_value)
            else:
                try:
                    cred = credentials.Certificate(json.loads(cred_value))
                except json.JSONDecodeError as e:
                    raise RuntimeError(
                        f"FIREBASE_CREDENTIALS_JSON is not valid JSON (len={len(cred_value)}, "
                        f"starts={repr(cred_value[:80])}). Paste full service account JSON."
                    ) from e
            firebase_admin.initialize_app(cred, {"projectId": FIREBASE_PROJECT_ID})
        self._db = firestore.client()
        logger.info("Connected to Firebase Firestore")

    def _col(self, name: str):
        self._connect()
        return self._db.collection(name)

    def _stream(self, query) -> list:
        return [_doc(d) for d in query.stream()]

    # ── Runners ───────────────────────────────────────────────────────────────

    def get_runner(self, runner_id: str) -> dict:
        return _doc(self._col("runners").document(runner_id).get())

    def find_runner_by_phone(self, phone: str) -> dict:
        needle = normalize_phone(phone)
        docs = (self._col("runners")
                .where("phone_normalized", "==", needle)
                .where("status", "==", "Active")
                .limit(1).stream())
        for d in docs:
            return _doc(d)
        return None

    def find_any_runner_by_phone(self, phone: str) -> dict:
        needle = normalize_phone(phone)
        for d in self._col("runners").where("phone_normalized", "==", needle).limit(1).stream():
            return _doc(d)
        return None

    def get_all_active_runners(self) -> list:
        return self._stream(self._col("runners").where("status", "==", "Active"))

    def get_coach_runners(self, coach_id: str) -> list:
        return self._stream(
            self._col("runners")
            .where("coach_id", "==", coach_id)
            .where("status", "==", "Active")
        )

    def create_runner(self, data: dict) -> str:
        runner_id = _make_id("B")
        phone = data.get("phone", "")
        self._col("runners").document(runner_id).set({
            "runner_id":       runner_id,
            "name":            data.get("name", ""),
            "phone":           phone,
            "phone_normalized": normalize_phone(phone),
            "coach_id":        data.get("coach_id", ""),
            "race_goal":       data.get("race_goal", ""),
            "race_date":       data.get("race_date", ""),
            "weekly_days":     data.get("weekly_days", ""),
            "injuries":        data.get("injuries", ""),
            "fitness_level":   data.get("fitness_level", ""),
            "start_date":      data.get("start_date", ""),
            "status":          data.get("status", "Active"),
            "prompt_version":  "v1",
            "payment_status":  data.get("payment_status", "Paid"),
            "monthly_fee":     data.get("monthly_fee", ""),
            "onboarded":       "TRUE" if data.get("onboarded") else "FALSE",
            "notes":           data.get("notes", ""),
            "created_at":      _now_ist(),
        })
        logger.info(f"Created runner {runner_id} — {data.get('name')}")
        return runner_id

    def update_runner(self, runner_id: str, fields: dict):
        if "phone" in fields:
            fields["phone_normalized"] = normalize_phone(fields["phone"])
        self._col("runners").document(runner_id).update(fields)
        logger.info(f"Updated runner {runner_id}: {list(fields.keys())}")

    # ── Training Plans — CRUD ────────────────────────────────────────────────

    def get_runner_plans(self, runner_id: str, from_date: str = "", to_date: str = "") -> list:
        """Plans for a runner in a date range, sorted by date.
        Filters in Python to avoid requiring composite Firestore indexes."""
        plans = self._stream(self._col("training_plans").where("runner_id", "==", runner_id))
        if from_date:
            plans = [p for p in plans if p.get("date", "") >= from_date]
        if to_date:
            plans = [p for p in plans if p.get("date", "") <= to_date]
        return sorted(plans, key=lambda p: p.get("date", ""))

    def create_plan(self, data: dict) -> str:
        """Upsert — if a plan already exists for this runner on this date, update it."""
        runner_id = data.get("runner_id", "")
        plan_date = data.get("date", "")

        if runner_id and plan_date:
            existing = [p for p in self._stream(
                self._col("training_plans").where("runner_id", "==", runner_id)
            ) if p.get("date") == plan_date]
            if existing:
                plan_id = existing[0].get("plan_id") or existing[0].get("_id", "")
                update_fields = {
                    "day_type":     data.get("day_type", "Run"),
                    "session_type": data.get("session_type", "Easy Run"),
                    "distance_km":  str(data.get("distance_km", "")),
                    "intensity":    data.get("intensity", "Zone 2"),
                    "rpe_target":   data.get("rpe_target", "4-5"),
                    "coach_notes":  data.get("coach_notes", ""),
                }
                self._col("training_plans").document(plan_id).update(update_fields)
                logger.info(f"Upserted plan {plan_id} for runner {runner_id} on {plan_date}")
                return plan_id

        plan_id = data.get("plan_id") or f"PLAN_{str(uuid.uuid4())[:8].upper()}"
        self._col("training_plans").document(plan_id).set({
            "plan_id":        plan_id,
            "runner_id":      runner_id,
            "date":           plan_date,
            "day_type":       data.get("day_type", "Run"),
            "session_type":   data.get("session_type", "Easy Run"),
            "distance_km":    str(data.get("distance_km", "")),
            "duration_min":   str(data.get("duration_min", "")),
            "intensity":      data.get("intensity", "Zone 2"),
            "rpe_target":     data.get("rpe_target", "4-5"),
            "coach_notes":    data.get("coach_notes", ""),
            "sent":           "FALSE",
            "sent_at":        "",
            "completed":      "FALSE",
            "actual_distance": "",
            "rpe_actual":     "",
            "runner_feedback": "",
            "flags":          "",
        })
        return plan_id

    def update_plan(self, plan_id: str, fields: dict):
        self._col("training_plans").document(plan_id).update(fields)

    def delete_plan(self, plan_id: str):
        self._col("training_plans").document(plan_id).delete()

    def delete_all_runner_plans(self, runner_id: str, from_date: str = "") -> int:
        """Delete all future plans for a runner. Returns number deleted."""
        plans = self._stream(self._col("training_plans").where("runner_id", "==", runner_id))
        if from_date:
            plans = [p for p in plans if p.get("date", "") >= from_date]
        for p in plans:
            pid = p.get("plan_id") or p.get("_id", "")
            if pid:
                self._col("training_plans").document(pid).delete()
        logger.info(f"Deleted {len(plans)} plans for runner {runner_id} from {from_date}")
        return len(plans)

    # ── Training Plans ────────────────────────────────────────────────────────

    def get_todays_plan(self, runner_id: str) -> dict:
        today = date.today().isoformat()
        for d in (self._col("training_plans")
                  .where("runner_id", "==", runner_id)
                  .where("date", "==", today)
                  .limit(1).stream()):
            return _doc(d)
        return None

    def get_all_todays_plans(self) -> dict:
        today = date.today().isoformat()
        result = {}
        for d in self._col("training_plans").where("date", "==", today).stream():
            plan = _doc(d)
            result[plan["runner_id"]] = plan
        return result

    def mark_plan_sent(self, plan_id: str):
        self._col("training_plans").document(plan_id).update({
            "sent": "TRUE",
            "sent_at": _now_ist(),
        })

    def update_plan_feedback(self, runner_id: str, message: str):
        today = date.today().isoformat()
        for d in (self._col("training_plans")
                  .where("runner_id", "==", runner_id)
                  .where("date", "==", today)
                  .limit(1).stream()):
            d.reference.update({"runner_feedback": message})
            break

    def get_runners_with_no_feedback_today(self) -> list:
        today = date.today().isoformat()
        no_feedback_ids = {
            _doc(d)["runner_id"]
            for d in (self._col("training_plans")
                      .where("date", "==", today)
                      .where("sent", "==", "TRUE").stream())
            if not _doc(d).get("runner_feedback")
        }
        return [r for r in self.get_all_active_runners() if r["runner_id"] in no_feedback_ids]

    def get_todays_summary(self, coach_id: str) -> dict:
        runner_ids = {r["runner_id"] for r in self.get_coach_runners(coach_id)}
        todays = [p for p in self.get_all_todays_plans().values() if p["runner_id"] in runner_ids]
        return {
            "total":     len(todays),
            "completed": sum(1 for p in todays if str(p.get("completed", "")).upper() == "TRUE"),
            "flagged":   [p for p in todays if p.get("flags")],
        }

    # ── Coach Configs ─────────────────────────────────────────────────────────

    def get_coach_config(self, coach_id: str) -> dict:
        config = _doc(self._col("coaches").document(coach_id).get())
        if config:
            version = config.get("active_prompt_version", "v1")
            config["active_system_prompt"] = config.get(f"system_prompt_{version}", "")
        return config

    def find_coach_by_phone(self, phone: str) -> dict:
        needle = normalize_phone(phone)
        for d in (self._col("coaches")
                  .where("coach_phone_normalized", "==", needle)
                  .where("status", "==", "Active")
                  .limit(1).stream()):
            return _doc(d)
        return None

    def get_all_active_coaches(self) -> list:
        return self._stream(self._col("coaches").where("status", "==", "Active"))

    # ── Rules & Corrections ───────────────────────────────────────────────────

    def get_active_rules(self, coach_id: str) -> list:
        return self._stream(
            self._col("rules")
            .where("coach_id", "==", coach_id)
            .where("status", "==", "Active")
        )

    def add_rule(self, coach_id: str, rule: str, source: str, raw_message: str = ""):
        rule_id = f"RULE_{str(uuid.uuid4())[:6].upper()}"
        self._col("rules").document(rule_id).set({
            "rule_id":        rule_id,
            "coach_id":       coach_id,
            "date_added":     date.today().isoformat(),
            "situation":      raw_message,
            "wrong_response": "",
            "correct_response": "",
            "rule_derived":   rule,
            "status":         "Active",
            "source":         source,
        })

    def get_all_coach_rules(self, coach_id: str) -> list:
        rules = self._stream(self._col("rules").where("coach_id", "==", coach_id))
        return sorted(rules, key=lambda r: (r.get("status","Active") != "Active", r.get("date_added","")))

    def archive_rule(self, rule_id: str):
        self._col("rules").document(rule_id).update({"status": "Archived"})

    def restore_rule(self, rule_id: str):
        self._col("rules").document(rule_id).update({"status": "Active"})

    def delete_rule(self, rule_id: str):
        self._col("rules").document(rule_id).delete()

    def update_coach_prompt(self, coach_id: str, new_prompt: str) -> str:
        config = self.get_coach_config(coach_id)
        if not config:
            return None
        version = config.get("active_prompt_version", "v1")
        try:
            ver_num = int(version.replace("v", "")) + 1
        except Exception:
            ver_num = 2
        new_version = f"v{ver_num}"
        self._col("coaches").document(coach_id).update({
            f"system_prompt_{new_version}":      new_prompt,
            f"system_prompt_{new_version}_date": date.today().isoformat(),
            "active_prompt_version":             new_version,
        })
        logger.info(f"Coach {coach_id} prompt updated to {new_version}")
        return new_version

    def restore_prompt_version(self, coach_id: str, version: str):
        self._col("coaches").document(coach_id).update({"active_prompt_version": version})

    # ── Conversation Log ──────────────────────────────────────────────────────

    def get_last_n_messages(self, runner_id: str, n: int = 5) -> list:
        msgs = self._stream(
            self._col("conversations").where("runner_id", "==", runner_id)
        )
        msgs.sort(key=lambda m: m.get("timestamp", ""))
        return msgs[-n:]

    def is_within_session_window(self, runner_id: str) -> bool:
        """True if the runner sent an inbound message within the last 24 hours.
        If so, WhatsApp allows free-form send_text instead of templates."""
        from datetime import datetime
        msgs = self.get_last_n_messages(runner_id, n=10)
        for m in reversed(msgs):
            if m.get("direction") != "inbound" or not m.get("message"):
                continue
            try:
                ts = datetime.strptime(m["timestamp"], "%Y-%m-%d %H:%M:%S")
                return (datetime.now() - ts).total_seconds() < 86400
            except Exception:
                continue
        return False

    def get_all_recent_messages(self, n: int = 3) -> dict:
        all_msgs: dict = {}
        for m in self._stream(self._col("conversations")):
            rid = m.get("runner_id", "")
            all_msgs.setdefault(rid, []).append(m)
        return {
            rid: sorted(msgs, key=lambda m: m.get("timestamp", ""))[-n:]
            for rid, msgs in all_msgs.items()
        }

    def log_conversation(self, runner_id: str, coach_id: str, inbound: str, outbound: str, intent: str):
        ts = _now_ist()
        base_id = f"LOG_{str(uuid.uuid4())[:6].upper()}"
        col = self._col("conversations")
        for log_id, direction, message in [
            (base_id,       "inbound",  inbound),
            (base_id + "_r","outbound", outbound),
        ]:
            col.document(log_id).set({
                "log_id":            log_id,
                "timestamp":         ts,
                "runner_id":         runner_id,
                "coach_id":          coach_id,
                "direction":         direction,
                "message":           message,
                "message_type":      intent,
                "handled_by":        "agent",
                "escalated":         False,
                "escalation_reason": "",
            })

    # ── System Prompts (dynamic, editable from dashboard) ────────────────────

    def get_system_prompt(self, prompt_id: str):
        return _doc(self._col("system_prompts").document(prompt_id).get())

    def upsert_system_prompt(self, prompt_id: str, content: str,
                             changed_by: str = "system", reason: str = "") -> int:
        doc_ref = self._col("system_prompts").document(prompt_id)
        existing = _doc(doc_ref.get())
        version = (existing.get("version", 0) + 1) if existing else 1

        # Keep last 20 versions for undo
        history = existing.get("versions", []) if existing else []
        if existing:
            history = [{"version": existing["version"],
                        "content": existing["content"],
                        "changed_at": existing.get("updated_at", ""),
                        "changed_by": existing.get("last_changed_by", "system"),
                        "reason": existing.get("last_reason", "")}] + history
        history = history[:20]

        doc_ref.set({
            "prompt_id":       prompt_id,
            "content":         content,
            "version":         version,
            "updated_at":      _now_ist(),
            "last_changed_by": changed_by,
            "last_reason":     reason,
            "versions":        history,
        })
        logger.info(f"System prompt '{prompt_id}' updated to v{version} by {changed_by}")
        return version

    def revert_system_prompt(self, prompt_id: str, to_version: int) -> bool:
        existing = self.get_system_prompt(prompt_id)
        if not existing:
            return False
        for v in existing.get("versions", []):
            if v["version"] == to_version:
                self.upsert_system_prompt(prompt_id, v["content"],
                                          changed_by="undo",
                                          reason=f"Reverted to v{to_version}")
                return True
        return False

    def get_all_system_prompts(self) -> list:
        return self._stream(self._col("system_prompts"))

    # ── Onboarding Sessions (persistent across restarts) ─────────────────────

    def get_onboarding_session(self, phone: str) -> dict:
        return _doc(self._col("onboarding_sessions").document(phone).get())

    def save_onboarding_session(self, phone: str, session: dict):
        self._col("onboarding_sessions").document(phone).set({
            **{k: v for k, v in session.items() if k != "_id"},
            "updated_at": _now_ist(),
        })

    def delete_onboarding_session(self, phone: str):
        self._col("onboarding_sessions").document(phone).delete()

    # ── Runner Memory (compact daily summary) ────────────────────────────────

    def get_runner_memory(self, runner_id: str) -> dict:
        return _doc(self._col("runner_memory").document(runner_id).get())

    def save_runner_memory(self, runner_id: str, memory: dict):
        self._col("runner_memory").document(runner_id).set({
            "runner_id":    runner_id,
            "last_updated": _now_ist(),
            **memory,
        })
        logger.info(f"Saved memory for runner {runner_id}")

    def get_all_runner_conversations(self, runner_id: str, limit: int = 200) -> list:
        """All conversations for a runner, sorted oldest→newest, capped for memory building."""
        msgs = self._stream(self._col("conversations").where("runner_id", "==", runner_id))
        msgs = [m for m in msgs if m.get("message")]
        msgs.sort(key=lambda m: m.get("timestamp", ""))
        return msgs[-limit:]

    # ── Platform Log ──────────────────────────────────────────────────────────

    def log_platform_event(self, event_type: str, runner_id: str, coach_id: str,
                           details: str, status: str = "success"):
        self._col("platform_events").add({
            "timestamp":  _now_ist(),
            "event_type": event_type,
            "runner_id":  runner_id,
            "coach_id":   coach_id,
            "details":    details,
            "status":     status,
        })


# Singleton — same name as old sheets.py singleton so imports are drop-in
sheets = FirebaseClient()
