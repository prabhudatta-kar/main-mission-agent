import httpx
from config.settings import WATI_API_URL, WATI_API_TOKEN


class WhatsAppClient:
    def __init__(self):
        self._base = WATI_API_URL
        self._headers = {
            "Authorization": f"Bearer {WATI_API_TOKEN}",
            "Content-Type": "application/json"
        }

    async def send_text(self, phone: str, message: str):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self._base}/api/v1/sendSessionMessage/{phone}",
                headers=self._headers,
                json={"messageText": message}
            )

    async def send_template(self, phone: str, template_name: str, variables: dict):
        params = [{"name": k, "value": str(v)} for k, v in variables.items()]
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self._base}/api/v1/sendTemplateMessage",
                headers=self._headers,
                json={
                    "template_name": template_name,
                    "broadcast_name": template_name,
                    "receivers": [{"whatsappNumber": phone, "customParams": params}]
                }
            )


whatsapp = WhatsAppClient()
