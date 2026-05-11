"""
Seed the running coach knowledge base into Firebase system_prompts.
Run whenever the KB file is updated.

Usage: python -m scripts.seed_coaching_kb
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from integrations.firebase_db import sheets

KB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "agents", "running_coach_knowledge_base.md")

if __name__ == "__main__":
    with open(KB_PATH, "r") as f:
        content = f.read()

    version = sheets.upsert_system_prompt(
        "coaching_knowledge", content,
        changed_by="seed_script",
        reason="Running coach knowledge base seeded from MD file"
    )
    print(f"✓ Seeded coaching_knowledge to Firebase — version {version}")
    print(f"  {len(content):,} characters / ~{len(content)//4:,} tokens")
