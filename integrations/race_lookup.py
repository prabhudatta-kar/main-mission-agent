"""
Race calendar lookup with Firebase caching + web search fallback.

Flow:
  1. Fuzzy-match runner's input against Firebase `races` collection
  2. If no match → web search + LLM extract → store in Firebase
  3. Return normalised {name, date, city, distances} or None

Firebase document (races/{race_id}):
  name        — canonical name e.g. "Tata Mumbai Marathon"
  aliases     — ["Mumbai Marathon", "TMM", "mumbai marathon"]
  date        — "YYYY-MM-DD"
  city        — "Mumbai"
  distances   — ["42.2km", "21.1km", "10km"]
  url         — race website if known
  source      — "seeded" | "web_search"
  updated_at  — timestamp
"""
import difflib
import logging
import re

import httpx

from config.settings import OBSERVATIONS_MODEL
from integrations.firebase_db import sheets
from integrations.llm import llm

logger = logging.getLogger(__name__)


# ── Firebase helpers ──────────────────────────────────────────────────────────

def get_all_races() -> list:
    return sheets._stream(sheets._col("races"))


def upsert_race(race: dict) -> str:
    """Store or update a race. race_id = slugified name."""
    name    = race.get("name", "")
    race_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    doc_ref = sheets._col("races").document(race_id)
    from integrations.firebase_db import _now_ist
    doc_ref.set({**race, "race_id": race_id, "updated_at": _now_ist()}, merge=True)
    logger.info(f"Race upserted: {name} ({race_id})")
    return race_id


# ── Fuzzy match ───────────────────────────────────────────────────────────────

def _all_terms(race: dict) -> list[str]:
    terms = [race.get("name", "").lower()]
    terms += [a.lower() for a in race.get("aliases", [])]
    return [t for t in terms if t]


def find_race_in_db(query: str):
    """Return best-matching race from Firebase, or None if no good match."""
    races = get_all_races()
    if not races:
        return None

    query_lower = query.lower().strip()
    best_score  = 0.0
    best_race   = None

    for race in races:
        for term in _all_terms(race):
            score = difflib.SequenceMatcher(None, query_lower, term).ratio()
            if score > best_score:
                best_score = score
                best_race  = race

    # 0.6 threshold — loose enough to catch typos, tight enough to avoid false matches
    return best_race if best_score >= 0.6 else None


# ── Web search fallback ───────────────────────────────────────────────────────

async def _web_search(query: str) -> str:
    """Fetch DuckDuckGo HTML results for the query. Returns raw text snippet."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8,
                follow_redirects=True,
            )
            # Extract visible text from result snippets
            text  = resp.text
            snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', text, re.DOTALL)
            titles = re.findall(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', text, re.DOTALL)
            combined = " | ".join(
                re.sub(r"<[^>]+>", "", t + " " + s)
                for t, s in zip(titles[:5], snips[:5])
            )
            return combined[:3000]
    except Exception as e:
        logger.warning(f"Web search failed for '{query}': {e}")
        return ""


async def _llm_extract(race_name: str, search_snippet: str) :
    """Ask LLM to extract structured race data from search results."""
    from datetime import date
    prompt = f"""Extract details for the running race: "{race_name}"

Search results:
{search_snippet or 'No search results available. Use your training knowledge.'}

Today is {date.today().isoformat()}. Only include future races or races within the last year.

Return ONLY valid JSON (no markdown):
{{
  "name": "canonical full race name",
  "aliases": ["common abbreviations or alternate names"],
  "date": "YYYY-MM-DD (next upcoming edition, or most recent if not announced)",
  "city": "city name",
  "distances": ["42.2km", "21.1km"],
  "url": "official website if known, else empty string",
  "confident": true
}}
If you genuinely cannot determine the race details, return {{"confident": false}}."""

    try:
        raw = await llm.complete([
            {"role": "system", "content": "Extract structured race data. Return only valid JSON."},
            {"role": "user",   "content": prompt},
        ], model=OBSERVATIONS_MODEL, max_tokens=400)
        raw  = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        import json
        data = json.loads(raw)
        if not data.get("confident", True):
            return None
        data.pop("confident", None)
        return data
    except Exception as e:
        logger.warning(f"LLM race extraction failed for '{race_name}': {e}")
        return None


# ── Main entry point ──────────────────────────────────────────────────────────

async def lookup_race(query: str) :
    """
    Find a race by name/alias. Checks Firebase first, then web searches
    and stores the result for future lookups.
    Returns {name, date, city, distances} or None.
    """
    if not query or len(query) < 3:
        return None

    # 1. Try Firebase
    match = find_race_in_db(query)
    if match:
        logger.info(f"Race found in DB: {match['name']} for query '{query}'")
        return match

    # 2. Web search + LLM extract
    logger.info(f"Race '{query}' not in DB — searching web")
    snippet = await _web_search(f"{query} India marathon running race date 2026")
    race    = await _llm_extract(query, snippet)

    if race and race.get("name") and race.get("date"):
        race["source"] = "web_search"
        upsert_race(race)
        logger.info(f"Stored new race from web search: {race['name']}")
        return race

    logger.info(f"Could not resolve race: '{query}'")
    return None
