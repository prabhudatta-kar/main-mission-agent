"""
Coaching knowledge base access.

The full KB lives in Firebase (system_prompts.coaching_knowledge).
This module provides get_coaching_context(intent, message) which returns
the relevant section(s) to inject into the LLM prompt — keeping token
usage manageable by selecting only what the current conversation needs.

Sections returned:
  always   → core_principles (Part XX + philosophy distilled, ~300 tokens)
  injury   → injury_section  (Part XI — injury table + decision tree)
  nutrition → nutrition_section (Part X — nutrition facts)
  question  → physiology + workout toolbox excerpts (Parts II–V key points)
  feedback  → recovery_section (Part IX — recovery hierarchy + signs)
  missed    → mental_section  (Part XVI — dealing with setbacks)
"""
import logging
import re

from agents.prompt_store import get_prompt

logger = logging.getLogger(__name__)

_NUTRITION_KEYWORDS = {
    "eat", "food", "carb", "protein", "diet", "fuel", "nutrition", "calorie",
    "hydrat", "water", "gel", "supplement", "weight", "fast", "meal",
}

_INJURY_KEYWORDS = {
    "pain", "hurt", "injury", "sore", "tight", "achilles", "knee", "shin",
    "plantar", "it band", "hamstring", "stress fracture", "tendon", "niggle",
    "physio", "physiotherapist", "doctor",
}

_WORKOUT_KEYWORDS = {
    "zone", "tempo", "interval", "fartlek", "threshold", "vo2", "pace",
    "speed", "workout", "session", "training", "plan", "mileage", "long run",
    "easy run", "recovery run", "stride", "hill", "rpe", "heart rate",
}


def _keyword_match(text: str, keywords: set) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def get_coaching_context(intent: str, message: str) -> str:
    """
    Return coaching knowledge context appropriate for this message.
    Always includes core principles. Adds specific sections based on
    intent and keywords in the message.
    """
    kb = get_prompt("coaching_knowledge")
    if not kb:
        return ""

    sections = []

    # Core principles — always included (~300 tokens)
    core = _extract_section(kb, "PART XX")
    if not core:
        core = _extract_section(kb, "PART I")
    if core:
        sections.append(f"## Coaching principles to apply:\n{core[:1200]}")

    # Intent-specific sections
    if intent == "injury_flag" or _keyword_match(message, _INJURY_KEYWORDS):
        inj = _extract_section(kb, "PART XI")
        if inj:
            sections.append(f"## Injury guidance:\n{inj[:1500]}")

    if _keyword_match(message, _NUTRITION_KEYWORDS):
        nut = _extract_section(kb, "PART X")
        if nut:
            sections.append(f"## Nutrition guidance:\n{nut[:1200]}")

    if intent == "question" and _keyword_match(message, _WORKOUT_KEYWORDS):
        workout = _extract_section(kb, "PART V")
        if workout:
            sections.append(f"## Workout guidance:\n{workout[:1500]}")
        phys = _extract_section(kb, "PART II")
        if phys:
            sections.append(f"## Physiology:\n{phys[:800]}")

    if intent in ("feedback", "missed_session"):
        rec = _extract_section(kb, "PART IX")
        if rec:
            sections.append(f"## Recovery guidance:\n{rec[:1000]}")

    return "\n\n".join(sections)


def _extract_section(kb: str, part_header: str) -> str:
    """Extract the text of a PART section from the KB."""
    pattern = rf"(## {re.escape(part_header)}.*?)(?=\n## PART|\Z)"
    m = re.search(pattern, kb, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Try without ## prefix
    pattern2 = rf"(#{re.escape(part_header)}.*?)(?=\n#PART|\n## PART|\Z)"
    m2 = re.search(pattern2, kb, re.DOTALL | re.IGNORECASE)
    return m2.group(1).strip() if m2 else ""
