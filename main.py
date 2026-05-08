import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request

from agents.master_agent import handle_incoming
from config.settings import WEBHOOK_SECRET_TOKEN
from integrations.razorpay import razorpay_webhook, verify_signature
from routers.dashboard import router as dashboard_router
from routers.test_ui import router as test_router
from scheduler.jobs import start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    logger.info("Scheduler started")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(dashboard_router)
app.include_router(test_router)

# Stores the last raw Wati webhook payload for debugging
_last_webhook: dict = {}


@app.post("/webhook")
async def webhook(request: Request, token: str = Query(default="")):
    if WEBHOOK_SECRET_TOKEN and token != WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()

    # Store for debugging — visit /webhook/last to verify Wati is reaching the server
    global _last_webhook
    _last_webhook = data

    msg_type = data.get("type", "")
    if msg_type not in ("text", "message", ""):
        return {"status": "ignored"}

    await handle_incoming(data)
    return {"status": "ok"}


@app.get("/webhook/last")
async def webhook_last():
    """Shows the last payload received from Wati — use to verify webhook is configured."""
    return _last_webhook or {"info": "No webhook received yet. Configure Wati → Settings → Webhooks."}


@app.post("/razorpay/webhook")
async def razorpay(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if signature and not verify_signature(raw_body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(raw_body)
    await razorpay_webhook(data)
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
