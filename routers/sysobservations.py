"""
/sysobservations — internal dashboard for system watcher observations.
Shows the last 14 days of AI-generated improvement analysis.
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from agents.system_watcher import get_recent_observations, run_system_watcher

router = APIRouter()


@router.get("/sysobservations", response_class=HTMLResponse)
async def sysobservations_page():
    obs_list = get_recent_observations(limit=14)
    cards = ""
    for obs in obs_list:
        date_str = obs.get("date", "")
        summary  = obs.get("summary", "")
        priority = obs.get("top_priority", "")
        count    = obs.get("convo_count", 0)

        issues_html = ""
        for issue in obs.get("issues", []):
            sev   = issue.get("severity", "medium")
            sev_color = {"high": "#ff4444", "medium": "#ff9800", "low": "#4caf50"}.get(sev, "#999")
            issues_html += f"""
            <div class="issue">
              <div class="issue-header">
                <span class="badge" style="background:{sev_color}">{sev.upper()}</span>
                <span class="issue-type">{issue.get('type','').replace('_',' ')}</span>
                <strong>{issue.get('title','')}</strong>
              </div>
              <p>{issue.get('description','')}</p>
              {f'<blockquote>{issue.get("example","")}</blockquote>' if issue.get('example') else ''}
              <div class="fix">💡 {issue.get('suggested_fix','')}</div>
            </div>"""

        wins_html = ""
        for win in obs.get("wins", []):
            wins_html += f'<div class="win">✅ <strong>{win.get("title","")}</strong> — {win.get("description","")}</div>'

        cards += f"""
        <div class="card">
          <div class="card-header">
            <span class="date">{date_str}</span>
            <span class="count">{count} conversations analysed</span>
          </div>
          <p class="summary">{summary}</p>
          {f'<div class="priority">🎯 Top priority: {priority}</div>' if priority else ''}
          {'<h3>Issues</h3>' + issues_html if issues_html else ''}
          {'<h3>Wins</h3>' + wins_html if wins_html else ''}
        </div>"""

    if not cards:
        cards = '<div class="empty">No observations yet — the system watcher runs nightly. Click "Run Now" to trigger manually.</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>System Observations — Main Mission</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e0e0e0;min-height:100vh}}
  .topbar{{background:#1a1d27;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2a2d3a}}
  .topbar h1{{font-size:18px;font-weight:700;color:#fff}}
  .topbar a{{color:#aaa;text-decoration:none;font-size:13px}}
  .run-btn{{background:#5c6bc0;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:13px;cursor:pointer;font-weight:600}}
  .run-btn:hover{{background:#4a57a8}}
  .run-btn:disabled{{background:#333;color:#666;cursor:default}}
  .container{{max-width:900px;margin:0 auto;padding:24px 16px}}
  .card{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:12px;padding:20px;margin-bottom:20px}}
  .card-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}}
  .date{{font-size:16px;font-weight:700;color:#fff}}
  .count{{font-size:12px;color:#888;background:#252836;padding:4px 10px;border-radius:20px}}
  .summary{{color:#bbb;font-size:14px;line-height:1.6;margin-bottom:12px}}
  .priority{{background:#1e2a1e;border-left:3px solid #4caf50;padding:8px 12px;border-radius:4px;font-size:13px;color:#81c784;margin-bottom:16px}}
  h3{{font-size:13px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.5px;margin:16px 0 8px}}
  .issue{{background:#12151f;border:1px solid #2a2d3a;border-radius:8px;padding:12px;margin-bottom:8px}}
  .issue-header{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
  .badge{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;color:#fff}}
  .issue-type{{font-size:11px;color:#888;text-transform:capitalize}}
  .issue p{{font-size:13px;color:#bbb;line-height:1.5;margin-bottom:6px}}
  blockquote{{border-left:2px solid #444;padding-left:10px;font-size:12px;color:#888;font-style:italic;margin:6px 0}}
  .fix{{font-size:12px;color:#80cbc4;background:#0d1f1e;padding:6px 10px;border-radius:4px;margin-top:4px}}
  .win{{font-size:13px;color:#c8e6c9;padding:8px 0;border-bottom:1px solid #1e2a1e}}
  .win:last-child{{border-bottom:none}}
  .empty{{text-align:center;color:#666;padding:60px 0;font-size:14px}}
  #toast{{position:fixed;bottom:20px;right:20px;background:#333;color:#fff;padding:10px 18px;border-radius:8px;font-size:13px;display:none}}
</style>
</head>
<body>
<div class="topbar">
  <h1>🔍 System Observations</h1>
  <div style="display:flex;align-items:center;gap:16px">
    <a href="/dashboard">← Dashboard</a>
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
    const res = await fetch('/sysobservations/run', {{method:'POST'}});
    const d = await res.json();
    toast(d.ok ? 'Analysis complete — refresh to see results' : (d.error || 'Failed'));
  }} catch(e) {{ toast('Error: ' + e.message); }}
  finally {{ btn.disabled = false; btn.textContent = 'Run Now'; }}
}}
function toast(msg) {{
  const el = document.getElementById('toast');
  el.textContent = msg; el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 4000);
}}
</script>
</body>
</html>"""


@router.post("/sysobservations/run")
async def run_watcher_now():
    """Manually trigger the system watcher — useful for testing."""
    try:
        await run_system_watcher()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
