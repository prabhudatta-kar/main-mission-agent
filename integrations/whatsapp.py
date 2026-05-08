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

    async def send_text(self, phone: str, message: str):
        if not message or not message.strip():
            logger.error(f"send_text called with empty message for {phone} — skipping")
            return
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
                logger.info(f"Sent text to {clean_phone} — Wati response: {resp.text[:300]}")
            except httpx.HTTPStatusError as e:
                logger.error(f"WhatsApp send_text failed for {phone}: HTTP {e.response.status_code} — {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"WhatsApp send_text request error for {phone}: {e}")

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


whatsapp = WhatsAppClient()
