from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agents.master_agent import identify_sender
from agents.onboarding_agent import is_onboarding, start_onboarding, handle_onboarding
from agents.prompts import build_runner_prompt
from integrations.sheets import sheets
from integrations.llm import llm
from utils.intent_classifier import classify_intent
from utils.helpers import normalize_phone

router = APIRouter(prefix="/test")


class ChatRequest(BaseModel):
    phone: str
    message: str
    name: str = "New Runner"
    coach_id: str = ""


@router.get("/", response_class=HTMLResponse)
async def test_ui():
    return _HTML


@router.get("/coaches")
async def list_coaches():
    coaches = sheets.get_all_active_coaches()
    return [{"id": c["coach_id"], "name": c["coach_name"]} for c in coaches]


@router.post("/chat")
async def test_chat(req: ChatRequest):
    phone = normalize_phone(req.phone)
    sender = identify_sender(phone)

    if sender["type"] == "runner":
        runner_data = sender["data"]
        if str(runner_data.get("onboarded", "TRUE")).upper() == "FALSE":
            if not is_onboarding(phone):
                start_onboarding(phone, sender["coach_id"],
                                 name=runner_data.get("name", ""), runner_id=sender["id"])
            response = await handle_onboarding(phone, req.message)
            return {"sender_type": "onboarding", "intent": None, "response": response}

        runner_id = sender["id"]
        coach_id = sender["coach_id"]
        runner_data = sheets.get_runner(runner_id)
        todays_plan = sheets.get_todays_plan(runner_id)
        recent_messages = sheets.get_last_n_messages(runner_id, n=5)
        coach_config = sheets.get_coach_config(coach_id)
        active_rules = sheets.get_active_rules(coach_id)

        prompt = build_runner_prompt(
            system_prompt=coach_config.get("active_system_prompt", ""),
            rules=active_rules,
            runner=runner_data,
            plan=todays_plan,
            history=recent_messages,
            incoming=req.message,
        )
        intent = classify_intent(req.message)
        response = await llm.complete(prompt)
        return {"sender_type": "runner", "intent": intent, "response": response}

    elif sender["type"] == "coach":
        return {
            "sender_type": "coach",
            "intent": None,
            "response": "Coach message received. (Coach flow not simulated in test UI yet.)",
        }

    else:
        # Unknown phone — start or continue onboarding
        if not req.coach_id:
            return {
                "sender_type": "unknown",
                "intent": None,
                "response": "Select a coach from the panel above to start onboarding this number.",
            }
        if not is_onboarding(phone):
            start_onboarding(phone, req.coach_id, name=req.name or "New Runner")
        response = await handle_onboarding(phone, req.message)
        return {"sender_type": "onboarding", "intent": None, "response": response}


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Main Mission — Test Console</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0b141a;height:100vh;display:flex;flex-direction:column;overflow:hidden}

.header{background:#202c33;color:#e9edef;padding:12px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0}
.avatar{width:40px;height:40px;background:#00a884;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px}
.header h2{font-size:16px;font-weight:600}
.header p{font-size:12px;color:#8696a0;margin-top:2px}

.phone-bar{background:#111b21;padding:8px 16px;display:flex;align-items:center;gap:8px;flex-shrink:0;border-bottom:1px solid #2a3942}
.phone-bar label{color:#8696a0;font-size:12px;white-space:nowrap}
.phone-bar input{flex:1;background:#2a3942;border:none;border-radius:8px;padding:7px 12px;color:#e9edef;font-size:14px;outline:none}
.phone-bar input::placeholder{color:#8696a0}
.badge{font-size:11px;padding:3px 9px;border-radius:10px;background:#2a3942;color:#8696a0;white-space:nowrap;font-weight:500;cursor:default}
.badge.runner{background:#00a884;color:#fff}
.badge.coach{background:#5b45db;color:#fff}
.badge.unknown{background:#555;color:#ccc}
.badge.onboarding{background:#f0a500;color:#fff}

.onboard-panel{background:#0d1f27;border-bottom:1px solid #2a3942;padding:8px 16px;display:none;gap:8px;align-items:center;flex-wrap:wrap}
.onboard-panel.visible{display:flex}
.onboard-panel label{color:#8696a0;font-size:12px;white-space:nowrap}
.onboard-panel input,.onboard-panel select{background:#2a3942;border:none;border-radius:8px;padding:6px 10px;color:#e9edef;font-size:13px;outline:none}
.onboard-panel input{width:160px}
.onboard-panel select{min-width:160px}
.onboard-panel .hint{font-size:11px;color:#f0a500;margin-left:4px}

.messages{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:6px}
.empty-hint{text-align:center;color:#8696a0;font-size:13px;margin:auto;line-height:1.6}

.bubble{max-width:68%;padding:8px 12px 6px;border-radius:8px;font-size:14px;line-height:1.5;word-wrap:break-word}
.bubble.sent{align-self:flex-end;background:#005c4b;color:#e9edef;border-top-right-radius:2px}
.bubble.received{align-self:flex-start;background:#202c33;color:#e9edef;border-top-left-radius:2px}
.bubble .meta{font-size:11px;color:#8696a0;margin-top:4px}
.bubble.sent .meta{text-align:right}

.input-bar{background:#202c33;padding:10px 16px;display:flex;gap:8px;align-items:flex-end;flex-shrink:0}
.input-bar textarea{flex:1;background:#2a3942;border:none;border-radius:10px;padding:10px 14px;color:#e9edef;font-size:15px;resize:none;outline:none;max-height:120px;font-family:inherit;line-height:1.4}
.input-bar textarea::placeholder{color:#8696a0}
.send-btn{width:44px;height:44px;background:#00a884;border:none;border-radius:50%;color:#fff;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.send-btn:disabled{background:#2a3942;cursor:default}

@keyframes spin{to{transform:rotate(360deg)}}
.spin{display:inline-block;animation:spin .9s linear infinite}
</style>
</head>
<body>

<div class="header">
  <div class="avatar">🏃</div>
  <div>
    <h2>Main Mission Agent</h2>
    <p>Test Console — no WhatsApp needed</p>
  </div>
</div>

<div class="phone-bar">
  <label>Sending as:</label>
  <input id="phone" type="text" placeholder="+919876543210">
  <span id="badge" class="badge">—</span>
</div>

<div class="onboard-panel" id="onboard-panel">
  <label>Name:</label>
  <input id="runner-name" type="text" placeholder="Runner's name">
  <label>Coach:</label>
  <select id="coach-select"><option value="">Loading…</option></select>
  <span class="hint">↑ New number — fill these to start onboarding</span>
</div>

<div class="messages" id="messages">
  <div class="empty-hint">
    Enter a <strong style="color:#e9edef">runner's phone</strong> to chat with the agent.<br>
    Enter an <strong style="color:#e9edef">unknown number</strong> to test the onboarding flow.
  </div>
</div>

<div class="input-bar">
  <textarea id="input" rows="1" placeholder="Type a message…"></textarea>
  <button class="send-btn" id="send-btn" onclick="send()">&#9658;</button>
</div>

<script>
const phoneEl  = document.getElementById('phone');
const inputEl  = document.getElementById('input');
const msgsEl   = document.getElementById('messages');
const badgeEl  = document.getElementById('badge');
const sendBtn  = document.getElementById('send-btn');
const panel    = document.getElementById('onboard-panel');
const nameEl   = document.getElementById('runner-name');
const coachEl  = document.getElementById('coach-select');

// Load coaches for dropdown
fetch('/test/coaches')
  .then(r => r.json())
  .then(coaches => {
    coachEl.innerHTML = coaches.length
      ? '<option value="">Select coach…</option>' + coaches.map(c =>
          `<option value="${c.id}">${c.name} (${c.id})</option>`).join('')
      : '<option value="">No coaches in sheet yet</option>';
  })
  .catch(() => { coachEl.innerHTML = '<option value="">Could not load coaches</option>'; });

inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

async function send() {
  const phone   = phoneEl.value.trim();
  const message = inputEl.value.trim();
  if (!phone || !message) return;

  document.querySelector('.empty-hint')?.remove();
  bubble(message, 'sent', '');
  inputEl.value = '';
  inputEl.style.height = 'auto';
  sendBtn.disabled = true;
  sendBtn.innerHTML = '<span class="spin">&#8987;</span>';
  const typingId = bubble('…', 'received', '');

  try {
    const res = await fetch('/test/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        phone,
        message,
        name: nameEl.value.trim() || 'New Runner',
        coach_id: coachEl.value,
      })
    });
    const data = await res.json();
    rmBubble(typingId);

    const type = data.sender_type || 'unknown';
    badgeEl.className = 'badge ' + type;
    badgeEl.textContent = type;

    // Show onboarding panel for unknown/onboarding senders
    panel.classList.toggle('visible', type === 'unknown' || type === 'onboarding');

    const meta = data.intent ? 'intent: ' + data.intent : '';
    bubble(data.response, 'received', meta);
  } catch (err) {
    rmBubble(typingId);
    bubble('Error: ' + err.message, 'received', 'error');
  }

  sendBtn.disabled = false;
  sendBtn.innerHTML = '&#9658;';
  inputEl.focus();
}

let n = 0;
function bubble(text, side, meta) {
  const id = 'b' + n++;
  const el = document.createElement('div');
  el.id = id;
  el.className = 'bubble ' + side;
  el.innerHTML = text.replace(/\\n/g, '<br>') +
    (meta ? '<div class="meta">' + meta + '</div>' : '');
  msgsEl.appendChild(el);
  msgsEl.scrollTop = msgsEl.scrollHeight;
  return id;
}
function rmBubble(id) { document.getElementById(id)?.remove(); }
</script>
</body>
</html>
"""
