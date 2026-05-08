"""
/coachobservations/{coach_id} — per-coach day-wise observation dashboard for super admins.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from agents.coach_watcher import get_coach_observations, run_coach_watcher
from integrations.firebase_db import sheets

router = APIRouter()


@router.get("/coachobservations", response_class=HTMLResponse)
async def coach_obs_index():
    """Index page: list all coaches with a link to their observations."""
    coaches = sheets.get_all_active_coaches()
    rows = ""
    for c in coaches:
        cid   = c.get("coach_id", "")
        name  = c.get("name", cid)
        email = c.get("operatorEmail") or c.get("email") or "—"
        rows += f"""
        <a class="coach-row" href="/coachobservations/{cid}">
          <div>
            <div class="coach-name">{name}</div>
            <div class="coach-email">{email}</div>
          </div>
          <span class="arrow">→</span>
        </a>"""

    if not rows:
        rows = '<div class="empty">No active coaches found.</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coach Observations — Main Mission</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e0e0e0;min-height:100vh}}
.topbar{{background:#1a1d27;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2a2d3a}}
.topbar h1{{font-size:18px;font-weight:700;color:#fff}}
.topbar a{{color:#aaa;text-decoration:none;font-size:13px}}
.container{{max-width:700px;margin:0 auto;padding:24px 16px}}
h2{{font-size:14px;color:#666;text-transform:uppercase;letter-spacing:.5px;margin-bottom:16px}}
.coach-row{{display:flex;align-items:center;justify-content:space-between;background:#1a1d27;border:1px solid #2a2d3a;border-radius:10px;padding:16px 20px;margin-bottom:10px;text-decoration:none;color:inherit;transition:border-color .15s}}
.coach-row:hover{{border-color:#5c6bc0}}
.coach-name{{font-size:15px;font-weight:600;color:#fff}}
.coach-email{{font-size:12px;color:#666;margin-top:2px}}
.arrow{{color:#5c6bc0;font-size:18px}}
.empty{{text-align:center;color:#666;padding:60px 0;font-size:14px}}
</style>
</head>
<body>
<div class="topbar">
  <h1>👁 Coach Observations</h1>
  <a href="/dashboard">← Dashboard</a>
</div>
<div class="container">
  <h2>Select a coach</h2>
  {rows}
</div>
</body>
</html>""")


@router.get("/coachobservations/{coach_id}", response_class=HTMLResponse)
async def coach_obs_detail(coach_id: str):
    config     = sheets.get_coach_config(coach_id)
    coach_name = (config or {}).get("name", coach_id) if config else coach_id
    obs_list   = get_coach_observations(coach_id, limit=30)

    cards = ""
    for obs in obs_list:
        date_str     = obs.get("date", "")
        summary      = obs.get("summary", "")
        convo_count  = obs.get("convo_count", 0)
        runner_count = obs.get("runner_count", 0)
        msg_sent     = obs.get("message_sent", "")
        coach_reply  = obs.get("coach_reply", "")

        # Patterns
        patterns_html = ""
        for p in obs.get("patterns", []):
            freq_color = "#ff9800" if p.get("frequency") == "recurring" else "#5c6bc0"
            patterns_html += f"""
            <div class="item">
              <span class="freq-badge" style="background:{freq_color}">{p.get('frequency','once')}</span>
              <strong>{p.get('title','')}</strong>
              <p>{p.get('description','')}</p>
            </div>"""

        # Style gaps
        gaps_html = ""
        for g in obs.get("style_gaps", []):
            gaps_html += f"""
            <div class="item gap">
              <div class="gap-situation"><strong>Situation:</strong> {g.get('situation','')}</div>
              <div class="gap-ai"><strong>AI did:</strong> {g.get('current_ai_approach','')}</div>
              <div class="gap-q">❓ {g.get('question_for_coach','')}</div>
            </div>"""

        # Wins
        wins_html = "".join(
            f'<div class="win">✅ {w}</div>' for w in obs.get("wins", [])
        )

        # Coach exchange
        exchange_html = ""
        if msg_sent:
            exchange_html += f'<div class="msg-sent">📤 <em>{msg_sent}</em></div>'
        if coach_reply:
            exchange_html += f'<div class="msg-reply">💬 Coach replied: {coach_reply}</div>'
        elif msg_sent:
            exchange_html += '<div class="msg-pending">⏳ Awaiting coach reply</div>'

        cards += f"""
        <div class="card">
          <div class="card-header">
            <span class="date">{date_str}</span>
            <span class="meta">{runner_count} runners · {convo_count} messages</span>
          </div>
          <p class="summary">{summary}</p>
          {'<h3>Patterns</h3>' + patterns_html if patterns_html else ''}
          {'<h3>Style Gaps</h3>' + gaps_html if gaps_html else ''}
          {'<h3>Wins</h3>' + wins_html if wins_html else ''}
          {'<h3>Coach Q&amp;A</h3>' + exchange_html if exchange_html else ''}
        </div>"""

    if not cards:
        cards = '<div class="empty">No observations yet. The coach watcher runs nightly at 10 PM IST.</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{coach_name} — Coach Observations</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e0e0e0;min-height:100vh}}
.topbar{{background:#1a1d27;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2a2d3a;gap:16px;flex-wrap:wrap}}
.topbar h1{{font-size:18px;font-weight:700;color:#fff}}
.topbar-right{{display:flex;align-items:center;gap:16px}}
.topbar a{{color:#aaa;text-decoration:none;font-size:13px}}
.run-btn{{background:#5c6bc0;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:13px;cursor:pointer;font-weight:600}}
.run-btn:disabled{{background:#333;color:#666;cursor:default}}
.container{{max-width:900px;margin:0 auto;padding:24px 16px}}
.card{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:12px;padding:20px;margin-bottom:20px}}
.card-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px}}
.date{{font-size:16px;font-weight:700;color:#fff}}
.meta{{font-size:12px;color:#888;background:#252836;padding:4px 10px;border-radius:20px}}
.summary{{color:#bbb;font-size:14px;line-height:1.6;margin-bottom:12px}}
h3{{font-size:12px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.5px;margin:16px 0 8px}}
.item{{background:#12151f;border:1px solid #2a2d3a;border-radius:8px;padding:12px;margin-bottom:8px}}
.item strong{{color:#fff;font-size:13px;display:block;margin-bottom:4px}}
.item p{{font-size:13px;color:#bbb;line-height:1.5;margin:4px 0 0}}
.freq-badge{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;color:#fff;margin-right:6px}}
.gap-situation,.gap-ai{{font-size:12px;color:#bbb;margin-bottom:4px}}
.gap-situation strong,.gap-ai strong{{color:#888}}
.gap-q{{font-size:13px;color:#80cbc4;background:#0d1f1e;padding:6px 10px;border-radius:4px;margin-top:8px}}
.win{{font-size:13px;color:#c8e6c9;padding:6px 0;border-bottom:1px solid #1e2a1e}}
.win:last-child{{border-bottom:none}}
.msg-sent{{font-size:13px;color:#bbb;background:#1e2030;border-radius:6px;padding:10px 12px;margin-bottom:8px;font-style:italic}}
.msg-reply{{font-size:13px;color:#a5d6a7;background:#1e2a1e;border-radius:6px;padding:10px 12px;margin-bottom:8px}}
.msg-pending{{font-size:12px;color:#666;padding:4px 0}}
.empty{{text-align:center;color:#666;padding:60px 0;font-size:14px}}
#toast{{position:fixed;bottom:20px;right:20px;background:#333;color:#fff;padding:10px 18px;border-radius:8px;font-size:13px;display:none}}
</style>
</head>
<body>
<div class="topbar">
  <h1>👁 {coach_name} — Daily Observations</h1>
  <div class="topbar-right">
    <a href="/coachobservations">← All Coaches</a>
    <a href="/dashboard">Dashboard</a>
    <button class="run-btn" id="run-btn" onclick="runNow()">Run Now</button>
  </div>
</div>
<div class="container">
  {cards}
</div>
<div id="toast"></div>
<script>
async function runNow() {{
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = 'Running…';
  try {{
    const res = await fetch('/coachobservations/{coach_id}/run', {{method:'POST'}});
    const d   = await res.json();
    showToast(d.ok ? 'Done — refresh to see results' : (d.error || 'Failed'));
  }} catch(e) {{ showToast('Error: ' + e.message); }}
  finally {{ btn.disabled = false; btn.textContent = 'Run Now'; }}
}}
function showToast(msg) {{
  const el = document.getElementById('toast');
  el.textContent = msg; el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 4000);
}}
</script>
</body>
</html>""")


@router.post("/coachobservations/{coach_id}/run")
async def run_coach_obs_now(coach_id: str):
    """Manually trigger the coach watcher for one coach."""
    try:
        coach = sheets.get_coach_config(coach_id)
        if not coach:
            return JSONResponse({"ok": False, "error": "Coach not found"}, status_code=404)
        from agents.coach_watcher import _process_coach
        await _process_coach(coach)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
