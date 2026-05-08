"""
Strava activity fetcher — public activities only, no OAuth required.

Strava's current pages are Next.js client-side rendered, so detailed stats
(pace, HR, distance) are not in the initial HTML. We extract the activity
name from the page title and return a prompt note that tells the LLM to
ask the runner for specific numbers rather than guessing.
"""
import logging
import re

import httpx

logger = logging.getLogger(__name__)

STRAVA_ACTIVITY_RE = re.compile(r"https?://(?:www\.)?strava\.com/activities/(\d+)")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_strava_context(url: str) -> str:
    """
    Try to get basic context from a public Strava activity URL.
    Returns a short descriptive string to inject into the LLM prompt.
    Always returns something — never raises.
    """
    match = STRAVA_ACTIVITY_RE.search(url)
    if not match:
        return ""

    activity_id = match.group(1)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
            resp = await client.get(url, headers=_HEADERS)

        if resp.status_code == 401 or resp.status_code == 403:
            return (
                f"[Strava activity {activity_id}: private or login required — "
                f"ask the runner to share their key stats directly]"
            )

        if resp.status_code != 200:
            return f"[Strava activity {activity_id}: could not fetch (HTTP {resp.status_code})]"

        html = resp.text

        # Extract activity name from page title: "Morning Run | Strava" → "Morning Run"
        title_m = re.search(
            r"<title[^>]*>(.*?)\s*[\|—]\s*Strava\s*</title>",
            html,
            re.DOTALL | re.IGNORECASE,
        )
        activity_name = title_m.group(1).strip() if title_m else "activity"

        # Strava client-side renders the stats — they are not in the initial HTML.
        # We can only reliably get the activity name.
        logger.info(f"Strava: fetched title='{activity_name}' for activity {activity_id}")
        return (
            f"[Runner shared Strava activity: '{activity_name}' (ID {activity_id}). "
            f"Detailed stats (distance, pace, heart rate) are not accessible without Strava login. "
            f"Acknowledge the run by name and ask them to share the key numbers: "
            f"distance (km), average pace (min/km), and how it felt.]"
        )

    except httpx.TimeoutException:
        logger.warning(f"Strava fetch timed out for {url}")
        return f"[Strava link shared but request timed out — ask the runner for their stats directly]"
    except Exception as e:
        logger.warning(f"Strava fetch error for {url}: {e}")
        return f"[Strava link shared but could not be fetched — ask the runner for their stats directly]"
