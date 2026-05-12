import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request

from agents.master_agent import handle_incoming
from config.settings import WEBHOOK_SECRET_TOKEN, WHATSAPP_BUSINESS_PHONE
from integrations.razorpay import razorpay_webhook, verify_signature
from routers.auth import DashboardAuthMiddleware, router as auth_router
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
app.add_middleware(DashboardAuthMiddleware)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(sysobs_router)
app.include_router(coachobs_router)
app.include_router(test_router)

# Stores the last raw Wati webhook payload for debugging (set before auth so we can diagnose 401s)
_last_webhook: dict = {}
_last_webhook_meta: dict = {}   # token, headers, status for diagnosing auth failures

# In-process dedup (fast path) — cleared on restart, backed up by Firestore below
_processed_ids: set = set()
_MAX_DEDUP_SIZE = 500


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
    if msg_type not in ("text", "message", "image", ""):
        logger.info(f"Webhook ignored msg_type='{msg_type}'")
        return {"status": "ignored", "type": msg_type}

    # Deduplicate: Wati retries if we take >~7s; fire-and-forget so we reply instantly
    # In-memory check (fast) + Firestore check (survives restarts)
    global _processed_ids
    msg_id = data.get("id") or data.get("whatsappMessageId", "")
    if msg_id:
        if msg_id in _processed_ids:
            logger.info(f"Duplicate webhook ignored (memory): {msg_id}")
            return {"status": "duplicate"}
        # Firestore dedup — atomic set-if-not-exists using a dedicated collection
        from integrations.firebase_db import sheets as _sheets
        dedup_ref = _sheets._col("webhook_dedup").document(msg_id)
        dedup_doc = dedup_ref.get()
        if dedup_doc.exists:
            logger.info(f"Duplicate webhook ignored (firestore): {msg_id}")
            _processed_ids.add(msg_id)
            return {"status": "duplicate"}
        dedup_ref.set({"ts": asyncio.get_event_loop().time()})
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


@app.get("/payment-success")
async def payment_success(request: Request):
    from fastapi.responses import HTMLResponse
    wa_link = f"https://wa.me/{WHATSAPP_BUSINESS_PHONE}"
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>You're in — Main Mission</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e0e0e0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
.card{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:16px;padding:40px 32px;max-width:400px;width:100%;text-align:center}}
.tick{{font-size:64px;margin-bottom:16px;line-height:1}}
h1{{font-size:22px;font-weight:800;color:#fff;margin-bottom:8px}}
.sub{{font-size:14px;color:#888;line-height:1.6;margin-bottom:24px}}
.countdown{{font-size:13px;color:#5c6bc0;margin-bottom:20px}}
.wa-btn{{display:inline-flex;align-items:center;gap:10px;background:#25d366;color:#fff;text-decoration:none;border-radius:10px;padding:13px 26px;font-size:15px;font-weight:700}}
.wa-btn:hover{{background:#1ebe5d}}
</style>
</head>
<body>
<div class="card">
  <div class="tick">🎉</div>
  <h1>You're in!</h1>
  <p class="sub">Subscription confirmed. Your coach will have your training plan ready within 24 hours — everything happens over WhatsApp.</p>
  <p class="countdown" id="cd">Taking you back to WhatsApp in <strong id="secs">3</strong>s…</p>
  <a class="wa-btn" id="wa-btn" href="{wa_link}">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
    Open WhatsApp
  </a>
</div>
<script>
  var secs = 3;
  var t = setInterval(function() {{
    secs--;
    document.getElementById('secs').textContent = secs;
    if (secs <= 0) {{
      clearInterval(t);
      window.location.href = '{wa_link}';
    }}
  }}, 1000);
</script>
</body>
</html>""")


@app.get("/health")
async def health():
    return {"status": "ok"}
