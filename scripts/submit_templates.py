"""
Submit and check status of WhatsApp message templates via Wati API.

Usage:
    # Check status of all templates against Wati
    python -m scripts.submit_templates

    # Submit all missing/rejected templates
    python -m scripts.submit_templates --submit

    # Submit a single template
    python -m scripts.submit_templates --submit --only mm_morning_run

API:
    GET  /{tenantId}/api/v1/getMessageTemplates   — list existing templates
    POST /{tenantId}/api/v1/templates/create      — create a new template

Auth: WATI_API_KEY (from Wati Settings → API → Access Token)
      Different from WATI_API_TOKEN (the JWT session token)
"""

import asyncio
import os
import re
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from dotenv import load_dotenv

load_dotenv()

from templates.catalog import TEMPLATES
from scripts.generate_samples import SAMPLES

WATI_API_URL = os.getenv("WATI_API_URL", "")
WATI_API_KEY = os.getenv("WATI_API_KEY", "")     # for template management
WATI_API_TOKEN = os.getenv("WATI_API_TOKEN", "") # fallback (JWT session)

# Wati uses named vars {{first_name}}, not positional {{1}}
def _wati_body(catalog_body: str) -> str:
    """Convert Python format string {var} → Wati template {{var}}."""
    return re.sub(r"\{(\w+)\}", r"{{\1}}", catalog_body)


def _custom_params(variables: list, template_id: str) -> list:
    """Build customParams using sample values where available."""
    sample = SAMPLES.get(template_id, {})
    return [
        {"paramName": v, "paramValue": str(sample.get(v, v))}
        for v in variables
    ]


def _build_payload(template_id: str, tmpl: dict) -> dict:
    return {
        "id": "",
        "type": "template",
        "category": "UTILITY",
        "subCategory": "STANDARD",
        "buttonsType": "none",
        "WabaIdList": [],
        "buttons": [],
        "footer": "",
        "elementName": tmpl["wati_name"],
        "language": "en_US",
        "header": None,
        "customParams": _custom_params(tmpl["variables"], template_id),
        "body": _wati_body(tmpl["body"]),
        "creationMethod": 0,
    }


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "origin": "https://live.wati.io",
        "referer": "https://live.wati.io/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    }


async def fetch_wati_templates(client: httpx.AsyncClient, token: str) -> dict:
    r = await client.get(
        f"{WATI_API_URL}/api/v1/getMessageTemplates",
        headers=_headers(token),
        timeout=15,
    )
    r.raise_for_status()
    templates = r.json().get("messageTemplates", [])
    return {t["elementName"]: t for t in templates}


async def create_template(client: httpx.AsyncClient, token: str, template_id: str, tmpl: dict) -> dict:
    payload = _build_payload(template_id, tmpl)
    r = await client.post(
        f"{WATI_API_URL}/api/v1/templates/create",
        headers=_headers(token),
        json=payload,
        timeout=15,
    )
    return {"status": r.status_code, "body": r.text, "payload": payload}


async def main(submit: bool, only):
    if not WATI_API_URL or "placeholder" in WATI_API_URL:
        print("ERROR: WATI_API_URL not set in .env")
        sys.exit(1)

    if not WATI_API_TOKEN:
        print("ERROR: WATI_API_TOKEN not set in .env")
        sys.exit(1)
    token = WATI_API_TOKEN

    templates_to_process = {
        tid: tmpl for tid, tmpl in TEMPLATES.items()
        if only is None or tmpl["wati_name"] == only
    }
    if not templates_to_process:
        print(f"No template found with wati_name='{only}'")
        sys.exit(1)

    print()
    print("=" * 68)
    print("  MAIN MISSION — TEMPLATE STATUS")
    print(f"  {WATI_API_URL}")
    print("=" * 68)

    async with httpx.AsyncClient() as client:
        try:
            wati_templates = await fetch_wati_templates(client, token)
            print(f"\n  Found {len(wati_templates)} templates already in Wati.\n")
        except Exception as e:
            print(f"\n  ERROR fetching templates: {e}")
            sys.exit(1)

        # ── Status table ──────────────────────────────────────────────────
        needs_action = []
        print(f"  {'ST':<2}  {'STATUS':<12} {'WATI NAME':<30} SCENARIO")
        print(f"  {'──':<2}  {'──────────':<12} {'──────────':<30} {'──────────'}")

        for tid, tmpl in templates_to_process.items():
            wati_name = tmpl["wati_name"]
            wati_data = wati_templates.get(wati_name)
            if wati_data:
                status = wati_data.get("status", "UNKNOWN")
                icon = "✓" if status == "APPROVED" else ("⏳" if status == "PENDING" else "✗")
                print(f"  {icon}   {status:<12} {wati_name:<30} {tmpl['scenario'][:36]}")
                if status in ("REJECTED", "DELETED"):
                    needs_action.append((tid, tmpl))
            else:
                print(f"  ✗   {'MISSING':<12} {wati_name:<30} {tmpl['scenario'][:36]}")
                needs_action.append((tid, tmpl))

        print()

        if not needs_action:
            print("  All templates are submitted. Nothing to do.\n")
            return

        if not submit:
            print(f"  {len(needs_action)} template(s) need submitting.")
            print("  Run with --submit to create them via the Wati API.\n")
            return

        # ── Submit missing / rejected templates ───────────────────────────
        print(f"  Submitting {len(needs_action)} template(s)...\n")
        submitted, failed = [], []

        for tid, tmpl in needs_action:
            result = await create_template(client, token, tid, tmpl)
            name = tmpl["wati_name"]

            if result["status"] in (200, 201):
                print(f"  ✓ {name}")
                submitted.append(name)
            else:
                print(f"  ✗ {name}  HTTP {result['status']}: {result['body'][:120]}")
                failed.append(name)

        print()
        print(f"  Submitted: {len(submitted)}  Failed: {len(failed)}")
        if failed:
            print(f"\n  Failed: {failed}")
            print("  Common causes: template name already taken, policy violation,")
            print("  or wrong category. Try changing category to MARKETING if UTILITY fails.")
        else:
            print("\n  All submitted! Meta approval usually takes ~24 hours.")
            print("  Run without --submit to check status after approval.")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--submit", action="store_true", help="Actually call the API to create templates")
    parser.add_argument("--only", type=str, default=None, help="wati_name of a single template to process")
    args = parser.parse_args()
    asyncio.run(main(submit=args.submit, only=args.only))
