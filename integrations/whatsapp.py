import logging

import httpx

from config.settings import WATI_API_URL, WATI_API_TOKEN
from utils.helpers import normalize_phone

logger = logging.getLogger(__name__)


def _wati_phone(phone: str) -> str:
    """Normalize any phone format to the 12-digit form Wati requires (no + prefix)."""
    return normalize_phone(phone).lstrip("+")


class WhatsAppClient:
    def __init__(self):
        self._base = WATI_API_URL
        self._headers = {
            "Authorization": f"Bearer {WATI_API_TOKEN}",
            "Content-Type": "application/json",
        }

    async def send_text(self, phone: str, message: str) -> bool:
        """Returns True if delivered. Returns False if Wati rejects (e.g. ticket expired/closed)."""
        if not message or not message.strip():
            logger.error(f"send_text called with empty message for {phone} — skipping")
            return False
        clean_phone = _wati_phone(phone)
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self._base}/api/v1/sendSessionMessage/{clean_phone}",
                    headers=self._headers,
                    params={"messageText": message},
                    timeout=10,
                )
                resp.raise_for_status()
                try:
                    body = resp.json()
                except Exception:
                    body = {}
                if not body.get("result", True):
                    # Wati returns HTTP 200 but result:false when ticket is closed/expired
                    logger.warning(f"send_text rejected for {clean_phone}: {body.get('message', 'unknown')} (ticketStatus={body.get('ticketStatus', '?')})")
                    return False
                logger.info(f"Sent text to {clean_phone}")
                return True
            except httpx.HTTPStatusError as e:
                logger.error(f"WhatsApp send_text failed for {phone}: HTTP {e.response.status_code} — {e.response.text}")
                return False
            except httpx.RequestError as e:
                logger.error(f"WhatsApp send_text request error for {phone}: {e}")
                return False

    async def send_template(self, phone: str, template_name: str, variables: dict):
        clean_phone = _wati_phone(phone)
        parameters  = [{"name": k, "value": str(v)} for k, v in variables.items()]
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self._base}/api/v1/sendTemplateMessage",
                    headers=self._headers,
                    params={"whatsappNumber": clean_phone},
                    json={
                        "template_name":  template_name,
                        "broadcast_name": template_name,
                        "parameters":     parameters,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                logger.info(f"Sent template '{template_name}' to {clean_phone}")
            except httpx.HTTPStatusError as e:
                logger.error(f"WhatsApp send_template failed for {phone}: HTTP {e.response.status_code} — {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"WhatsApp send_template request error for {phone}: {e}")


    async def get_media_bytes(self, media_id: str) -> tuple[bytes, str]:
        """Download media from Wati. Returns (bytes, mime_type)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._base}/api/v1/getMedia/{media_id}",
                headers=self._headers,
                timeout=20,
                follow_redirects=True,
            )
            resp.raise_for_status()
            mime = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            return resp.content, mime


whatsapp = WhatsAppClient()


async def send_runner_message(runner: dict, message: str):
    """
    Send a proactive message to a runner.
    Uses free-form text if within the 24h session window,
    otherwise falls back to the mm_question_general approved template.

    Use this for ALL proactive sends (plan summaries, reminders, coach
    direct messages). Do NOT use it for replies to inbound messages —
    those are always within the window.
    """
    if not message or not message.strip():
        return

    from integrations.firebase_db import sheets as _sheets

    phone     = runner.get("phone", "")
    runner_id = runner.get("runner_id", "")
    first     = (runner.get("name") or "there").split()[0]
    if first == "New":
        first = "there"

    if _sheets.is_within_session_window(runner_id):
        delivered = await whatsapp.send_text(phone, message)
        if delivered:
            return
        logger.info(f"send_text rejected for {phone} (ticket closed despite active window) — falling back to template")

    # Template fallback — either session window expired, or send_text was rejected by Wati.
    # Template body: "{first_name}, {answer}"
    # Strip any greeting prefix that contains the runner's name to prevent doubling.
    import re
    answer = message.strip()
    if first and first != "there":
        for greeting in ("Hi ", "Hey ", "Hello ", ""):
            for sep in (", ", "! ", "! \n", ",\n", "\n"):
                prefix = greeting + first + sep
                if answer.startswith(prefix):
                    answer = answer[len(prefix):].lstrip()
                    break
            else:
                continue
            break
    # Wati template parameters reject newlines, tabs, and 5+ consecutive spaces.
    answer_clean = answer.replace("\n", " ").replace("\t", " ")
    answer_clean = re.sub(r" {5,}", "    ", answer_clean).strip()
    await whatsapp.send_template(
        phone=phone,
        template_name="mm_question_general",
        variables={"first_name": first, "answer": answer_clean[:1024]},
    )
    logger.info(f"Used template fallback for {phone}")
