import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request

from agents.master_agent import handle_incoming
from config.settings import WEBHOOK_SECRET_TOKEN
from integrations.razorpay import razorpay_webhook, verify_signature
from routers.coachobservations import router as coachobs_router
from routers.dashboard import router as dashboard_router
from routers.sysobservations import router as sysobs_router
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
app.include_router(sysobs_router)
app.include_router(coachobs_router)
app.include_router(test_router)

# Stores the last raw Wati webhook payload for debugging (set before auth so we can diagnose 401s)
_last_webhook: dict = {}
_last_webhook_meta: dict = {}   # token, headers, status for diagnosing auth failures

# Deduplicate Wati retries — Wati resends if we don't reply within ~7s; cache processed IDs
_processed_ids: set = set()
_MAX_DEDUP_SIZE = 500   # prevent unbounded growth


@app.post("/webhook")
async def webhook(request: Request, token: str = Query(default="")):
    # Capture body and meta BEFORE auth check so /webhook/last always shows what Wati sent
    try:
        data = await request.json()
    except Exception:
        data = {}

    global _last_webhook, _last_webhook_meta
    _last_webhook = data
    _last_webhook_meta = {
        "token_received": token or "(none)",
        "token_expected": WEBHOOK_SECRET_TOKEN or "(not set)",
        "auth_ok": not WEBHOOK_SECRET_TOKEN or token == WEBHOOK_SECRET_TOKEN,
        "content_type": request.headers.get("content-type", ""),
        "user_agent": request.headers.get("user-agent", ""),
    }

    if WEBHOOK_SECRET_TOKEN and token != WEBHOOK_SECRET_TOKEN:
        logger.warning(f"Webhook 401: received token='{token}', expected='{WEBHOOK_SECRET_TOKEN}'")
        raise HTTPException(status_code=401, detail="Unauthorized")

    msg_type = data.get("type", "")
    if msg_type not in ("text", "message", ""):
        logger.info(f"Webhook ignored msg_type='{msg_type}'")
        return {"status": "ignored", "type": msg_type}

    # Deduplicate: Wati retries if we take >~7s; fire-and-forget so we reply instantly
    global _processed_ids
    msg_id = data.get("id") or data.get("whatsappMessageId", "")
    if msg_id and msg_id in _processed_ids:
        logger.info(f"Duplicate webhook ignored: {msg_id}")
        return {"status": "duplicate"}
    if msg_id:
        _processed_ids.add(msg_id)
        if len(_processed_ids) > _MAX_DEDUP_SIZE:
            _processed_ids = set(list(_processed_ids)[-_MAX_DEDUP_SIZE // 2:])

    asyncio.create_task(handle_incoming(data))
    return {"status": "ok"}


@app.get("/webhook/last")
async def webhook_last():
    """Shows the last payload received from Wati — use to verify webhook is configured."""
    if not _last_webhook:
        return {"info": "No webhook received yet. Configure Wati → Settings → Webhooks."}
    return {"meta": _last_webhook_meta, "payload": _last_webhook}


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
