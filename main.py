import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request

from agents.master_agent import handle_incoming
from config.settings import WEBHOOK_SECRET_TOKEN
from integrations.razorpay import razorpay_webhook, verify_signature
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


@app.post("/webhook")
async def webhook(request: Request, token: str = Query(default="")):
    if WEBHOOK_SECRET_TOKEN and token != WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    msg_type = data.get("type", "")

    # Only process inbound text messages; skip delivery/read receipts etc.
    if msg_type not in ("text", "message", ""):
        return {"status": "ignored"}

    await handle_incoming(data)
    return {"status": "ok"}


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
