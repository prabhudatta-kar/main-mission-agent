"""
Seed Firebase with realistic test data.

    python -m scripts.seed_data
    python -m scripts.seed_data --reset   # clears existing data first
"""
import sys, os, argparse, uuid
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()

from integrations.firebase_db import FirebaseClient
from utils.helpers import normalize_phone

TODAY = "2026-05-07"
YESTERDAY = "2026-05-06"

# ── Coach ─────────────────────────────────────────────────────────────────────

COACH = {
    "coach_id": "COACH_A",
    "coach_name": "Prabhudatta Kar",
    "coach_phone": "+919777199410",
    "coach_phone_normalized": "+919777199410",
    "active_prompt_version": "v1",
    "system_prompt_v1": (
        "You are the AI coaching assistant for Main Mission, a running coaching platform in Bangalore, India. "
        "You represent Coach Prabhudatta and communicate with their runners on WhatsApp.\n\n"
        "Your role:\n"
        "- Deliver daily training instructions in a warm, motivating, personalised way\n"
        "- Collect workout feedback and log it accurately\n"
        "- Answer running-related questions confidently\n"
        "- Flag concerns (injury, dropout risk, overtraining) to the coach\n"
        "- Never replace the human coach — you support and amplify them\n\n"
        "Tone: Warm but direct. Like a knowledgeable friend who runs.\n"
        "Language: English with occasional Hindi words is fine (e.g. chalo, kya scene hai)\n"
        "Length: 2-4 sentences max. WhatsApp is conversational.\n\n"
        "Never give specific nutrition or medical advice. Always use the runner's name."
    ),
    "system_prompt_v1_date": "2026-01-10",
    "coaching_style": "Data-driven with warmth — pushes runners to their potential but listens when they need rest",
    "escalation_rules": "Escalate any mention of pain/injury, 3+ consecutive missed sessions, or expressed desire to quit",
    "status": "Active",
}

# ── Races ─────────────────────────────────────────────────────────────────────

RACES = {
    "ladakh":  {"name": "Ladakh Marathon",           "date": "2026-09-13", "distance": 42.2},
    "blr10k":  {"name": "TCS World 10K Bengaluru",   "date": "2026-08-02", "distance": 10},
    "mumbai":  {"name": "Tata Mumbai Marathon",       "date": "2027-01-17", "distance": 42.2},
}

# ── Runners ───────────────────────────────────────────────────────────────────
# 7 Ladakh Marathon · 7 Bengaluru 10K · 6 Mumbai Marathon

RUNNERS = [
    # ── Ladakh Marathon runners (18 weeks out) ───────────────────────────────
    {
        "runner_id": "RUN_001", "name": "Kiran Kumar",     "phone": "9845012345",
        "race": "ladakh", "fitness_level": "Advanced",
        "weekly_days": 5, "weekly_km": 65, "injuries": "None",
        "start_date": "2026-01-10", "monthly_fee": 3000,
        "notes": "Completed Bangalore Ultra 50K last year. Targeting sub-4hr at Ladakh.",
    },
    {
        "runner_id": "RUN_002", "name": "Priya Venkatesh",  "phone": "9901234567",
        "race": "ladakh", "fitness_level": "Intermediate",
        "weekly_days": 4, "weekly_km": 42, "injuries": "Left IT band — flares on long runs",
        "start_date": "2026-02-01", "monthly_fee": 2500,
        "notes": "First marathon attempt. Strong base but needs to manage IT band carefully.",
    },
    {
        "runner_id": "RUN_003", "name": "Arun Pillai",     "phone": "8892345678",
        "race": "ladakh", "fitness_level": "Advanced",
        "weekly_days": 6, "weekly_km": 72, "injuries": "None",
        "start_date": "2026-01-05", "monthly_fee": 3000,
        "notes": "Ex-state level 1500m runner. Transitioning to marathon. Very disciplined.",
    },
    {
        "runner_id": "RUN_004", "name": "Sunita Patel",    "phone": "7760123456",
        "race": "ladakh", "fitness_level": "Intermediate",
        "weekly_days": 4, "weekly_km": 35, "injuries": "Right plantar fasciitis — managed",
        "start_date": "2026-02-15", "monthly_fee": 2500,
        "notes": "Runs early morning before work. Very consistent with training.",
    },
    {
        "runner_id": "RUN_005", "name": "Siddharth Bose",  "phone": "9123456789",
        "race": "ladakh", "fitness_level": "Intermediate",
        "weekly_days": 5, "weekly_km": 48, "injuries": "None",
        "start_date": "2026-01-20", "monthly_fee": 2500,
        "notes": "Works in tech. High stress job — needs nudging on rest days.",
    },
    {
        "runner_id": "RUN_006", "name": "Kavitha Menon",   "phone": "8765012345",
        "race": "ladakh", "fitness_level": "Beginner",
        "weekly_days": 3, "weekly_km": 22, "injuries": "None",
        "start_date": "2026-03-01", "monthly_fee": 2000,
        "notes": "Very motivated but prone to overtraining. Needs to slow down on easy runs.",
    },
    {
        "runner_id": "RUN_007", "name": "Rahul Gupta",     "phone": "9654321098",
        "race": "ladakh", "fitness_level": "Advanced",
        "weekly_days": 6, "weekly_km": 80, "injuries": "Tight calves — monitor",
        "start_date": "2026-01-08", "monthly_fee": 3000,
        "notes": "Boston qualifier attempt (sub-3:10). Very data-focused, logs all sessions.",
    },

    # ── TCS Bengaluru 10K runners (12 weeks out) ─────────────────────────────
    {
        "runner_id": "RUN_008", "name": "Ananya Krishnan",  "phone": "9876501234",
        "race": "blr10k", "fitness_level": "Beginner",
        "weekly_days": 3, "weekly_km": 18, "injuries": "None",
        "start_date": "2026-03-10", "monthly_fee": 1500,
        "notes": "First race ever. Super excited. Needs lots of encouragement.",
    },
    {
        "runner_id": "RUN_009", "name": "Vikram Nair",     "phone": "8901234501",
        "race": "blr10k", "fitness_level": "Intermediate",
        "weekly_days": 4, "weekly_km": 30, "injuries": "None",
        "start_date": "2026-02-20", "monthly_fee": 2000,
        "notes": "Sub-55min goal for 10K. Good speed, endurance is the limiter.",
    },
    {
        "runner_id": "RUN_010", "name": "Deepa Nair",      "phone": "7012345678",
        "race": "blr10k", "fitness_level": "Intermediate",
        "weekly_days": 4, "weekly_km": 28, "injuries": "Right shin splints — recovering",
        "start_date": "2026-02-25", "monthly_fee": 2000,
        "notes": "Returned after 3-month injury break. Building carefully.",
    },
    {
        "runner_id": "RUN_011", "name": "Rohit Sharma",    "phone": "9812345670",
        "race": "blr10k", "fitness_level": "Beginner",
        "weekly_days": 3, "weekly_km": 15, "injuries": "None",
        "start_date": "2026-03-15", "monthly_fee": 1500,
        "notes": "Lost 8kg since starting. Very motivated by weight loss progress.",
    },
    {
        "runner_id": "RUN_012", "name": "Meera Reddy",     "phone": "8712345609",
        "race": "blr10k", "fitness_level": "Intermediate",
        "weekly_days": 4, "weekly_km": 32, "injuries": "None",
        "start_date": "2026-02-10", "monthly_fee": 2000,
        "notes": "Sub-52min PB holder. Back to racing after maternity break.",
    },
    {
        "runner_id": "RUN_013", "name": "Suresh Babu",     "phone": "7890123450",
        "race": "blr10k", "fitness_level": "Advanced",
        "weekly_days": 5, "weekly_km": 55, "injuries": "None",
        "start_date": "2026-01-25", "monthly_fee": 2500,
        "notes": "Sub-45min 10K target. Runs intervals twice a week on his own.",
    },
    {
        "runner_id": "RUN_014", "name": "Rashmi Joshi",    "phone": "9234567801",
        "race": "blr10k", "fitness_level": "Beginner",
        "weekly_days": 3, "weekly_km": 16, "injuries": "None",
        "start_date": "2026-03-20", "monthly_fee": 1500,
        "notes": "Doctor. Very irregular schedule — sometimes misses 2 days at a stretch.",
    },

    # ── Mumbai Marathon runners (36 weeks out, base building) ─────────────────
    {
        "runner_id": "RUN_015", "name": "Manish Agarwal",  "phone": "9345678012",
        "race": "mumbai", "fitness_level": "Intermediate",
        "weekly_days": 4, "weekly_km": 38, "injuries": "None",
        "start_date": "2026-04-01", "monthly_fee": 2500,
        "notes": "Corporate runner. Finished Hyderabad HM in 2:12. Target 4:30 at Mumbai full.",
    },
    {
        "runner_id": "RUN_016", "name": "Pooja Iyer",      "phone": "8456789012",
        "race": "mumbai", "fitness_level": "Beginner",
        "weekly_days": 3, "weekly_km": 20, "injuries": "Lower back — posture issue",
        "start_date": "2026-04-05", "monthly_fee": 2000,
        "notes": "Started running during lockdown. This will be her first marathon.",
    },
    {
        "runner_id": "RUN_017", "name": "Kartik Verma",    "phone": "7123456780",
        "race": "mumbai", "fitness_level": "Intermediate",
        "weekly_days": 4, "weekly_km": 40, "injuries": "None",
        "start_date": "2026-04-10", "monthly_fee": 2500,
        "notes": "Runs with a club on weekends. Social runner — enjoys the community aspect.",
    },
    {
        "runner_id": "RUN_018", "name": "Nandita Rao",     "phone": "9567890123",
        "race": "mumbai", "fitness_level": "Advanced",
        "weekly_days": 5, "weekly_km": 58, "injuries": "None",
        "start_date": "2026-03-25", "monthly_fee": 3000,
        "notes": "Sub-3:30 marathon target. Strong runner, needs work on pacing strategy.",
    },
    {
        "runner_id": "RUN_019", "name": "Shreya Gupta",    "phone": "8678901234",
        "race": "mumbai", "fitness_level": "Beginner",
        "weekly_days": 3, "weekly_km": 17, "injuries": "None",
        "start_date": "2026-04-15", "monthly_fee": 1500,
        "notes": "School teacher. Runs after school. Needs run/walk intervals for now.",
    },
    {
        "runner_id": "RUN_020", "name": "Varun Menon",     "phone": "7789012345",
        "race": "mumbai", "fitness_level": "Intermediate",
        "weekly_days": 4, "weekly_km": 35, "injuries": "Left knee — old ACL tear, cleared",
        "start_date": "2026-04-01", "monthly_fee": 2500,
        "notes": "Post ACL surgery (18 months ago). Cleared by physio. Monitor knee carefully.",
    },
]

# ── Today's Training Plans ────────────────────────────────────────────────────
# Wednesday 7 May 2026 — typical midweek session

PLANS = [
    # Ladakh runners — 18 weeks out, midweek quality
    {"runner_id": "RUN_001", "session": "Tempo Run",         "dist": 10, "intensity": "Threshold",    "rpe": "7-8", "notes": "2km warm-up, 6km at threshold, 2km cool-down. Heart rate cap 165.", "completed": True,  "feedback": "Done! Avg HR 161, felt controlled throughout. Legs still a bit heavy from Sunday.",  "flags": ""},
    {"runner_id": "RUN_002", "session": "Easy Run",          "dist": 8,  "intensity": "Zone 2",       "rpe": "4-5", "notes": "Flat route. If IT band feels tight after 5km, stop and walk back.", "completed": False, "feedback": "", "flags": ""},
    {"runner_id": "RUN_003", "session": "Interval Training", "dist": 12, "intensity": "VO2 Max",      "rpe": "8-9", "notes": "6x800m at 5K pace, 90s rest between. Focus on consistent splits.", "completed": True,  "feedback": "6x800 splits: 3:12, 3:14, 3:15, 3:13, 3:16, 3:11. Last rep was the fastest 💪", "flags": ""},
    {"runner_id": "RUN_004", "session": "Easy Run",          "dist": 6,  "intensity": "Zone 2",       "rpe": "4",   "notes": "Easy jog. Stop if plantar feels inflamed. Ice after.", "completed": True,  "feedback": "6km done. Plantar was fine. Wore the Brooks as you suggested, big difference!", "flags": ""},
    {"runner_id": "RUN_005", "session": "Tempo Run",         "dist": 8,  "intensity": "Threshold",    "rpe": "7-8", "notes": "4km easy, 4km tempo. Strong effort on the tempo section.", "completed": False, "feedback": "", "flags": ""},
    {"runner_id": "RUN_006", "session": "Easy Run",          "dist": 5,  "intensity": "Zone 2",       "rpe": "4-5", "notes": "SLOW. 7 min/km minimum. This is recovery, not a time trial.", "completed": False, "feedback": "", "flags": ""},
    {"runner_id": "RUN_007", "session": "Tempo Run",         "dist": 14, "intensity": "Threshold",    "rpe": "7-8", "notes": "2km warm-up, 10km at marathon pace (4:35/km target), 2km cool-down.", "completed": True,  "feedback": "Avg pace 4:32 for the 10km section. Calves felt tight in km 8-9, stretched well after.", "flags": "tight calves"},

    # Bengaluru 10K — 12 weeks out, speed phase
    {"runner_id": "RUN_008", "session": "Easy Run",          "dist": 4,  "intensity": "Zone 2",       "rpe": "4",   "notes": "30 min easy. Focus on breathing rhythm, not pace.", "completed": True,  "feedback": "Finished my 4km! Felt really good today, didn't stop once 🎉",                    "flags": ""},
    {"runner_id": "RUN_009", "session": "Interval Training", "dist": 8,  "intensity": "VO2 Max",      "rpe": "8-9", "notes": "8x400m at 10K race pace (4:45/km). 60s rest. Timed with watch.", "completed": False, "feedback": "", "flags": ""},
    {"runner_id": "RUN_010", "session": "Easy Run",          "dist": 5,  "intensity": "Zone 2",       "rpe": "4-5", "notes": "Flat terrain. Check shin after — if any pain, walk immediately.", "completed": False, "feedback": "my shin is acting up again after 3km, had to stop 😞", "flags": "injury"},
    {"runner_id": "RUN_011", "session": "Easy Run",          "dist": 4,  "intensity": "Zone 2",       "rpe": "4",   "notes": "4km easy. Can extend to 5km if it feels effortless.", "completed": True,  "feedback": "4km done in 28 min. Down 300g this week btw! Thanks coach 🙏",                    "flags": ""},
    {"runner_id": "RUN_012", "session": "Tempo Run",         "dist": 7,  "intensity": "Threshold",    "rpe": "7",   "notes": "1km warm-up, 5km at 10K race pace, 1km cool-down.", "completed": False, "feedback": "", "flags": ""},
    {"runner_id": "RUN_013", "session": "Interval Training", "dist": 10, "intensity": "VO2 Max",      "rpe": "9",   "notes": "5x1000m at 4:20/km. Full 2min rest. This builds the engine for 45min.", "completed": True,  "feedback": "5x1000 done. Splits ranged 4:15-4:22. Last one was tough but held form.", "flags": ""},
    {"runner_id": "RUN_014", "session": "Rest",              "dist": 0,  "intensity": "Rest",         "rpe": "0",   "notes": "Rest day. Walk if you want but no running.", "completed": False, "feedback": "", "flags": ""},

    # Mumbai runners — base building, easy mileage
    {"runner_id": "RUN_015", "session": "Easy Run",          "dist": 10, "intensity": "Zone 2",       "rpe": "4-5", "notes": "Comfortable 10km. Keep HR under 145. Listen to a podcast.", "completed": False, "feedback": "", "flags": ""},
    {"runner_id": "RUN_016", "session": "Easy Run",          "dist": 5,  "intensity": "Zone 2",       "rpe": "4",   "notes": "5km easy. Focus on upright posture — core engaged, shoulders relaxed.", "completed": True,  "feedback": "Done! Tried the posture cues you mentioned. Felt less back pain today 👍",          "flags": ""},
    {"runner_id": "RUN_017", "session": "Easy Run",          "dist": 8,  "intensity": "Zone 2",       "rpe": "4-5", "notes": "Easy 8km. If running with club today, tell them this is a Zone 2 day.", "completed": False, "feedback": "I skipped, had a late meeting sorry. Will double up tomorrow", "flags": ""},
    {"runner_id": "RUN_018", "session": "Tempo Run",         "dist": 12, "intensity": "Threshold",    "rpe": "7",   "notes": "3km easy, 6km at marathon pace (4:55/km), 3km easy. Lock in that race pace.", "completed": True,  "feedback": "6km tempo at 4:52 avg. Heart rate maxed at 158. Felt sustainable throughout.", "flags": ""},
    {"runner_id": "RUN_019", "session": "Easy Run",          "dist": 4,  "intensity": "Zone 2",       "rpe": "4",   "notes": "Run 2min, walk 1min. Total 4km. No pressure on pace.", "completed": False, "feedback": "", "flags": ""},
    {"runner_id": "RUN_020", "session": "Easy Run",          "dist": 6,  "intensity": "Zone 2",       "rpe": "4",   "notes": "6km easy. Any knee discomfort → stop immediately. No heroics.", "completed": False, "feedback": "Ran 4km, left knee felt a bit sore in the last km. Stopped as instructed", "flags": "injury"},
]

# ── Conversation History (yesterday's messages) ───────────────────────────────

CONVERSATIONS = [
    # RUN_001 — Kiran, yesterday's long run recap
    {"runner_id": "RUN_001", "direction": "inbound",  "message": "Coach done with yesterday's long run. 32km in 3:04. Felt strong till 26km then the legs got heavy. Had 3 gels.", "intent": "feedback"},
    {"runner_id": "RUN_001", "direction": "outbound", "message": "32km at that pace is excellent, Kiran! The fade after 26km is normal at this stage — your glycogen stores are running low. The gels are helping but you may need a 4th from 30km onwards at race day. Today's tempo will tell us a lot about your threshold. 💪", "intent": "feedback"},

    # RUN_002 — Priya, IT band concern
    {"runner_id": "RUN_002", "direction": "inbound",  "message": "IT band was really tight yesterday during the 14km run. Stopped at 11km and walked back. Got iced it and rolled.", "intent": "injury_flag"},
    {"runner_id": "RUN_002", "direction": "outbound", "message": "Right call stopping, Priya. Pushing through IT band pain only makes it worse. Today's easy 8km should be fine if it's not inflamed — but if you feel any pull at all, turn back. I've flagged this to your coach too. 🙏", "intent": "injury_flag"},

    # RUN_003 — Arun, great session
    {"runner_id": "RUN_003", "direction": "inbound",  "message": "Done! 6x800 in 3:10-3:14. Felt like I had more in the tank on the last two.", "intent": "feedback"},
    {"runner_id": "RUN_003", "direction": "outbound", "message": "Those splits are outstanding, Arun! Saving energy through the set means your aerobic base is solid. This is exactly where you need to be 18 weeks out. Tempo tomorrow — let's keep building 🔥", "intent": "feedback"},

    # RUN_007 — Rahul, calf tightness
    {"runner_id": "RUN_007", "direction": "inbound",  "message": "Done the tempo. But calves have been consistently tight for the past week. Not painful just very stiff after runs.", "intent": "feedback"},
    {"runner_id": "RUN_007", "direction": "outbound", "message": "Noted on the calves, Rahul. Consistent stiffness is an early warning sign — make sure you're doing 5 min calf raises and foam rolling daily. If this persists through this week I'll recommend a physio check before it escalates. I've logged this for your coach. 🙏", "intent": "feedback"},

    # RUN_008 — Ananya, beginner encouragement
    {"runner_id": "RUN_008", "direction": "inbound",  "message": "Hi! I completed my run today. Ran 3.5km without stopping first time ever!", "intent": "feedback"},
    {"runner_id": "RUN_008", "direction": "outbound", "message": "Ananya that's a massive milestone! 🎉 3.5km non-stop is exactly the kind of progress that builds into a 10K. Your body is adapting fast. Rest tomorrow, and we'll push to 4km on Friday.", "intent": "feedback"},

    # RUN_010 — Deepa, shin splints
    {"runner_id": "RUN_010", "direction": "inbound",  "message": "My shin is acting up again after 3km, had to stop 😞", "intent": "injury_flag"},
    {"runner_id": "RUN_010", "direction": "outbound", "message": "Deepa, thanks for stopping — that was the right call. Please rest today and tomorrow, ice the shin twice a day. I've flagged this to your coach and they'll be in touch. Don't push through shin pain 🙏", "intent": "injury_flag"},

    # RUN_017 — Kartik, missed session
    {"runner_id": "RUN_017", "direction": "inbound",  "message": "I skipped, had a late meeting sorry. Will double up tomorrow", "intent": "missed_session"},
    {"runner_id": "RUN_017", "direction": "outbound", "message": "No worries Kartik, life happens! One thing though — don't double up tomorrow. Just do today's session and move on. More mileage than planned often causes injury at this stage. See you on the roads tomorrow 🙂", "intent": "missed_session"},

    # RUN_020 — Varun, knee
    {"runner_id": "RUN_020", "direction": "inbound",  "message": "Ran 4km, left knee felt a bit sore in the last km. Stopped as instructed", "intent": "injury_flag"},
    {"runner_id": "RUN_020", "direction": "outbound", "message": "Varun, good decision stopping. Given your ACL history, any knee discomfort needs immediate attention — I've flagged this to your coach. Please rest tomorrow and ice the knee. They'll reach out shortly. 🙏", "intent": "injury_flag"},
]

# ── Seed function ─────────────────────────────────────────────────────────────

def seed(reset: bool = False):
    client = FirebaseClient()
    client._connect()
    db = client._db

    if reset:
        print("Clearing existing data...")
        for col in ["runners", "training_plans", "coaches", "rules", "conversations", "platform_events"]:
            for doc in db.collection(col).stream():
                doc.reference.delete()
        print("Cleared.\n")

    # Coach
    print("Adding coach...")
    db.collection("coaches").document(COACH["coach_id"]).set(COACH)
    print(f"  ✓ {COACH['coach_name']}")

    # Runners
    print(f"\nAdding {len(RUNNERS)} runners...")
    for r in RUNNERS:
        race = RACES[r["race"]]
        phone = r["phone"]
        doc = {
            "runner_id":        r["runner_id"],
            "name":             r["name"],
            "phone":            phone,
            "phone_normalized": normalize_phone(phone),
            "coach_id":         "COACH_A",
            "race_goal":        race["name"],
            "race_date":        race["date"],
            "weekly_days":      r["weekly_days"],
            "injuries":         r["injuries"],
            "fitness_level":    r["fitness_level"],
            "start_date":       r["start_date"],
            "status":           "Active",
            "prompt_version":   "v1",
            "payment_status":   "Paid",
            "monthly_fee":      str(r["monthly_fee"]),
            "onboarded":        "TRUE",
            "notes":            r["notes"],
            "created_at":       "2026-01-10 09:00:00",
        }
        db.collection("runners").document(r["runner_id"]).set(doc)
        print(f"  ✓ {r['name']:22} → {race['name']} ({race['date']})")

    # Training plans
    print(f"\nAdding {len(PLANS)} training plans for today ({TODAY})...")
    for p in PLANS:
        rid = p["runner_id"]
        runner = next(r for r in RUNNERS if r["runner_id"] == rid)
        plan_id = f"PLAN_{rid}_{TODAY}"
        completed = "TRUE" if p["completed"] else "FALSE"
        sent = "TRUE"
        doc = {
            "plan_id":        plan_id,
            "runner_id":      rid,
            "date":           TODAY,
            "day_type":       "Rest" if p["session"] == "Rest" else "Run",
            "session_type":   p["session"],
            "distance_km":    str(p["dist"]),
            "intensity":      p["intensity"],
            "rpe_target":     p["rpe"],
            "coach_notes":    p["notes"],
            "sent":           sent,
            "sent_at":        f"{TODAY} 06:00:00",
            "completed":      completed,
            "actual_distance": str(p["dist"]) if p["completed"] else "",
            "rpe_actual":     "",
            "runner_feedback": p["feedback"],
            "flags":          p["flags"],
        }
        db.collection("training_plans").document(plan_id).set(doc)
        status = "✓ completed" if p["completed"] else ("⚠ flagged" if p["flags"] else "⏳ pending")
        print(f"  {status:12} {runner['name']:22} {p['session']:20} {p['dist']}km")

    # Conversations
    print(f"\nAdding {len(CONVERSATIONS)} conversation entries...")
    ts = f"{YESTERDAY} 19:30:00"
    for i, c in enumerate(CONVERSATIONS):
        log_id = f"LOG_{c['runner_id']}_{i:03d}"
        runner = next(r for r in RUNNERS if r["runner_id"] == c["runner_id"])
        db.collection("conversations").document(log_id).set({
            "log_id":            log_id,
            "timestamp":         ts,
            "runner_id":         c["runner_id"],
            "coach_id":          "COACH_A",
            "direction":         c["direction"],
            "message":           c["message"],
            "message_type":      c["intent"],
            "handled_by":        "agent",
            "escalated":         "injury" in c["flags"] if "flags" in c else False,
            "escalation_reason": "",
        })
    print(f"  ✓ Done")

    # Summary
    print(f"""
{'='*60}
  Seed complete!

  Coach:    {COACH['coach_name']} ({COACH['coach_id']})
  Runners:  {len(RUNNERS)} total
            7 → Ladakh Marathon    (Sep 13 2026)
            7 → TCS Bengaluru 10K  (Aug 2 2026)
            6 → Tata Mumbai        (Jan 17 2027)
  Plans:    {len(PLANS)} training sessions added for {TODAY}
  Convos:   {len(CONVERSATIONS)} messages from yesterday

  Open the dashboard: http://localhost:8000/dashboard
{'='*60}""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Clear all existing data before seeding")
    args = parser.parse_args()
    seed(reset=args.reset)
