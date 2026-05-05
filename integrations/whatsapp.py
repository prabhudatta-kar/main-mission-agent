import logging

import httpx

from config.settings import WATI_API_URL, WATI_API_TOKEN

logger = logging.getLogger(__name__)


class WhatsAppClient:
    def __init__(self):
        self._base = WATI_API_URL
        self._headers = {
            "Authorization": f"Bearer {WATI_API_TOKEN}",
            "Content-Type": "application/json",
        }

    async def send_text(self, phone: str, message: str):
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self._base}/api/v1/sendSessionMessage/{phone}",
                    headers=self._headers,
                    json={"messageText": message},
                    timeout=10,
                )
                resp.raise_for_status()
                logger.info(f"Sent text to {phone}")
            except httpx.HTTPStatusError as e:
                logger.error(f"WhatsApp send_text failed for {phone}: HTTP {e.response.status_code} — {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"WhatsApp send_text request error for {phone}: {e}")

    async def send_template(self, phone: str, template_name: str, variables: dict):
        params = [{"name": k, "value": str(v)} for k, v in variables.items()]
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self._base}/api/v1/sendTemplateMessage",
                    headers=self._headers,
                    json={
                        "template_name": template_name,
                        "broadcast_name": template_name,
                        "receivers": [{"whatsappNumber": phone, "customParams": params}],
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                logger.info(f"Sent template '{template_name}' to {phone}")
            except httpx.HTTPStatusError as e:
                logger.error(f"WhatsApp send_template failed for {phone}: HTTP {e.response.status_code} — {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"WhatsApp send_template request error for {phone}: {e}")


whatsapp = WhatsAppClient()
