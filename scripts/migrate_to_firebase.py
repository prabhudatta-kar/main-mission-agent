"""
One-time migration: Google Sheets → Firebase Firestore.

Run after setting up Firebase and setting FIREBASE_CREDENTIALS_JSON + FIREBASE_PROJECT_ID:
    python -m scripts.migrate_to_firebase
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from integrations.firebase_db import FirebaseClient
from integrations.sheets_sync import SheetsClient
from utils.helpers import normalize_phone

def migrate():
    print("Connecting to Google Sheets...")
    src = SheetsClient()

    print("Connecting to Firebase...")
    dst = FirebaseClient()
    dst._connect()
    db = dst._db

    # ── Runners ──────────────────────────────────────────────────────────────
    runners = src._rows("Runners")
    print(f"\nMigrating {len(runners)} runners...")
    for r in runners:
        rid = r.get("runner_id") or r.get("runner_id", "")
        if not rid:
            continue
        phone = r.get("phone", "")
        r["phone_normalized"] = normalize_phone(phone)
        db.collection("runners").document(rid).set(r)
        print(f"  runner {rid} — {r.get('name')}")

    # ── Training Plans ────────────────────────────────────────────────────────
    plans = src._rows("Training_Plans")
    print(f"\nMigrating {len(plans)} training plans...")
    for p in plans:
        pid = p.get("plan_id", "")
        if not pid:
            continue
        db.collection("training_plans").document(pid).set(p)
    print(f"  done")

    # ── Coach Configs ─────────────────────────────────────────────────────────
    coaches = src._rows("Coach_Configs")
    print(f"\nMigrating {len(coaches)} coaches...")
    for c in coaches:
        cid = c.get("coach_id", "")
        if not cid:
            continue
        phone = c.get("coach_phone", "")
        c["coach_phone_normalized"] = normalize_phone(phone)
        db.collection("coaches").document(cid).set(c)
        print(f"  coach {cid} — {c.get('coach_name')}")

    # ── Rules & Corrections ───────────────────────────────────────────────────
    rules = src._rows("Rules_And_Corrections")
    print(f"\nMigrating {len(rules)} rules...")
    for r in rules:
        rid = r.get("rule_id", "")
        if not rid:
            continue
        db.collection("rules").document(rid).set(r)
    print(f"  done")

    # ── Conversation Log ──────────────────────────────────────────────────────
    convs = src._rows("Conversation_Log")
    print(f"\nMigrating {len(convs)} conversation entries...")
    for c in convs:
        lid = c.get("log_id", "")
        if not lid:
            continue
        db.collection("conversations").document(lid).set(c)
    print(f"  done")

    # ── Platform Log ──────────────────────────────────────────────────────────
    events = src._rows("Platform_Log")
    print(f"\nMigrating {len(events)} platform events...")
    for e in events:
        db.collection("platform_events").add(e)
    print(f"  done")

    print("\n✓ Migration complete. All Sheets data is now in Firebase.")
    print("  Sheets will now be used only for read-only coach view (sync with scripts/sync_to_sheets.py)")


if __name__ == "__main__":
    migrate()
