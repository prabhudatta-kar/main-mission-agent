from fastapi import FastAPI, Request
from agents.master_agent import handle_incoming
from integrations.razorpay import razorpay_webhook
from scheduler.jobs import start_scheduler

app = FastAPI()


@app.on_event("startup")
async def startup():
    start_scheduler()


@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    await handle_incoming(data)
    return {"status": "ok"}


@app.post("/razorpay/webhook")
async def razorpay(request: Request):
    data = await request.json()
    await razorpay_webhook(data)
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
