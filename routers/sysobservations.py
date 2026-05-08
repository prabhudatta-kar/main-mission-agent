"""
/sysobservations — internal dashboard for system watcher observations.
Shows the last 14 days of AI-generated improvement analysis with
one-click fix application and undo.
"""
import difflib
from datetime import datetime
from html import escape

import pytz
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from agents.prompt_store import reload_prompt
from agents.system_watcher import get_recent_observations, run_system_watcher
from integrations.firebase_db import sheets

_IST = pytz.timezone("Asia/Kolkata")


def _render_diff(old: str, new: str) -> str:
    """Return an HTML block showing a line-by-line diff of old vs new."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = list(difflib.ndiff(old_lines, new_lines))
    rows = []
    for line in diff:
        code = line[:2]
        text = escape(line[2:])
        if code == "+ ":
            rows.append(f'<div class="dl-add"><span class="dl-gutter">+</span>{text}</div>')
        elif code == "- ":
            rows.append(f'<div class="dl-del"><span class="dl-gutter">−</span>{text}</div>')
        elif code == "  ":
            rows.append(f'<div class="dl-ctx"><span class="dl-gutter"> </span>{text}</div>')
        # skip "? " hint lines
    return "\n".join(rows) if rows else "<em>No diff available</em>"

router = APIRouter()


# ── Fix apply / undo API ──────────────────────────────────────────────────────

@router.post("/sysobservations/apply/{obs_id}/{fix_idx}")
async def apply_fix(obs_id: str, fix_idx: int):
    """Apply a suggested fix — saves old value as undo snapshot."""
    doc_ref = sheets._col("system_observations").document(obs_id)
    doc     = doc_ref.get()
    if not doc.exists:
        return JSONResponse({"ok": False, "error": "Observation not found"}, status_code=404)

    data  = doc.to_dict()
    fixes = data.get("fixes", [])
    if fix_idx >= len(fixes):
        return JSONResponse({"ok": False, "error": "Fix index out of range"}, status_code=400)

    fix = fixes[fix_idx]
    if fix.get("applied"):
        return JSONResponse({"ok": False, "error": "Already applied"}, status_code=400)

    fix_type  = fix.get("fix_type")
    target_id = fix.get("target_id", "")
    content   = fix.get("new_content", "")

    undo_snapshot = None

    if fix_type == "prompt_update":
        current = sheets.get_system_prompt(target_id)
        # Store version + target only — old_content already lives on the fix itself,
        # so we don't duplicate it here (keeps the undo_snapshot small).
        undo_snapshot = {
            "type":    "prompt_update",
            "target":  target_id,
            "version": current.get("version") if current else None,
        }
        sheets.upsert_system_prompt(target_id, content,
                                    changed_by="observer_fix",
                                    reason=fix.get("description", ""))
        reload_prompt(target_id)

    elif fix_type == "rule_add":
        coaches = sheets.get_all_active_coaches()
        for c in coaches:
            sheets.add_rule(c["coach_id"], content,
                            source="observer_fix", raw_message=fix.get("description", ""))
        undo_snapshot = {"type": "rule_add", "rule_text": content}

    else:
        return JSONResponse({"ok": False, "error": f"Unknown fix_type: {fix_type}"}, status_code=400)

    fixes[fix_idx]["applied"]       = True
    fixes[fix_idx]["applied_at"]    = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
    fixes[fix_idx]["undo_snapshot"] = undo_snapshot

    try:
        doc_ref.update({"fixes": fixes})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Firestore update failed for obs {obs_id}: {e}")
        return JSONResponse({"ok": False, "error": f"Database write failed: {e}"}, status_code=500)

    return {"ok": True, "message": f"Fix applied: {fix.get('description','')}"}


@router.post("/sysobservations/undo/{obs_id}/{fix_idx}")
async def undo_fix(obs_id: str, fix_idx: int):
    """Undo a previously applied fix."""
    doc_ref = sheets._col("system_observations").document(obs_id)
    doc     = doc_ref.get()
    if not doc.exists:
        return JSONResponse({"ok": False, "error": "Observation not found"}, status_code=404)

    data  = doc.to_dict()
    fixes = data.get("fixes", [])
    if fix_idx >= len(fixes):
        return JSONResponse({"ok": False, "error": "Fix index out of range"}, status_code=400)

    fix = fixes[fix_idx]
    if not fix.get("applied"):
        return JSONResponse({"ok": False, "error": "Not yet applied"}, status_code=400)

    snap = fix.get("undo_snapshot", {})
    if not snap:
        return JSONResponse({"ok": False, "error": "No undo snapshot"}, status_code=400)

    snap_type = snap.get("type")

    if snap_type == "prompt_update":
        # old_content lives on the fix itself (not in snapshot, to keep docs small)
        target_id   = snap.get("target", "")
        old_content = fix.get("old_content", "")
        if not old_content:
            return JSONResponse({"ok": False, "error": "No old content to restore"}, status_code=400)
        sheets.upsert_system_prompt(target_id, old_content,
                                    changed_by="undo",
                                    reason=f"Undid fix: {fix.get('description','')}")
        reload_prompt(target_id)

    elif snap_type == "rule_add":
        coaches = sheets.get_all_active_coaches()
        for c in coaches:
            rules = sheets.get_all_coach_rules(c["coach_id"])
            for r in rules:
                if r.get("rule_derived") == snap.get("rule_text") and r.get("source") == "observer_fix":
                    sheets.delete_rule(r["rule_id"])

    fixes[fix_idx]["applied"]    = False
    fixes[fix_idx]["applied_at"] = None

    try:
        doc_ref.update({"fixes": fixes})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Firestore undo update failed for obs {obs_id}: {e}")
        return JSONResponse({"ok": False, "error": f"Database write failed: {e}"}, status_code=500)

    return {"ok": True, "message": "Fix undone"}


# ── Dashboard page ────────────────────────────────────────────────────────────

@router.get("/sysobservations", response_class=HTMLResponse)
async def sysobservations_page():
    obs_list = get_recent_observations(limit=14)
    cards    = ""

    for obs in obs_list:
        date_str = obs.get("date", "")
        summary  = obs.get("summary", "")
        priority = obs.get("top_priority", "")
        count    = obs.get("convo_count", 0)
        obs_id   = obs.get("obs_id", "")
        fixes    = obs.get("fixes", [])

        # Issues
        issues_html = ""
        for issue in obs.get("issues", []):
            sev       = issue.get("severity", "medium")
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
            </div>"""

        # Fixes
        fixes_html = ""
        for i, fix in enumerate(fixes):
            applied    = fix.get("applied", False)
            applied_at = fix.get("applied_at", "")
            fix_type   = fix.get("fix_type", "")
            label      = fix.get("target_label", fix.get("target_id", ""))
            btn_state  = 'disabled style="background:#2a5c2a"' if applied else ""
            undo_state = "" if applied else 'disabled style="opacity:.3"'
            badge_html = f'<span class="applied-badge">Applied {applied_at}</span>' if applied else ""

            # Prompt updates: show a diff; rule adds: show the new rule text
            if fix_type == "prompt_update" and fix.get("old_content"):
                preview_html = f"""
                <details class="fix-preview">
                  <summary>View diff (red = removed · green = added)</summary>
                  <div class="diff-block">{_render_diff(fix.get("old_content",""), fix.get("new_content",""))}</div>
                </details>"""
            elif fix.get("new_content"):
                preview_html = f"""
                <details class="fix-preview">
                  <summary>Preview content</summary>
                  <pre class="fix-content">{escape(fix.get("new_content","")[:1200])}</pre>
                </details>"""
            else:
                preview_html = ""

            fixes_html += f"""
            <div class="fix-card {'fix-applied' if applied else ''}">
              <div class="fix-header">
                <span class="fix-type-badge">{fix_type.replace('_',' ')}</span>
                <span class="fix-target">→ {label}</span>
                {badge_html}
              </div>
              <p class="fix-desc">{fix.get('description','')}</p>
              {preview_html}
              <div class="fix-actions">
                <button class="apply-btn" {btn_state}
                  onclick="applyFix('{obs_id}', {i}, this)">
                  {'✓ Applied' if applied else '⚡ Apply Fix'}
                </button>
                <button class="undo-btn" {undo_state}
                  onclick="undoFix('{obs_id}', {i}, this)">↩ Undo</button>
              </div>
            </div>"""

        # Wins
        wins_html = "".join(
            f'<div class="win">✅ <strong>{w.get("title","")}</strong> — {w.get("description","")}</div>'
            for w in obs.get("wins", [])
        )

        cards += f"""
        <div class="card">
          <div class="card-header">
            <span class="date">{date_str}</span>
            <span class="count">{count} conversations</span>
          </div>
          <p class="summary">{summary}</p>
          {f'<div class="priority">🎯 {priority}</div>' if priority else ''}
          {'<h3>Issues</h3>' + issues_html if issues_html else ''}
          {'<h3>Suggested Fixes</h3>' + fixes_html if fixes_html else ''}
          {'<h3>Wins</h3>' + wins_html if wins_html else ''}
        </div>"""

    if not cards:
        cards = '<div class="empty">No observations yet — click "Run Now" to trigger the first analysis.</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>System Observations — Main Mission</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e0e0e0;min-height:100vh}}
.topbar{{background:#1a1d27;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #2a2d3a;gap:12px;flex-wrap:wrap}}
.topbar h1{{font-size:18px;font-weight:700;color:#fff}}
.topbar-right{{display:flex;align-items:center;gap:16px}}
.topbar a{{color:#aaa;text-decoration:none;font-size:13px}}
.run-btn{{background:#5c6bc0;color:#fff;border:none;border-radius:6px;padding:8px 16px;font-size:13px;cursor:pointer;font-weight:600}}
.run-btn:hover{{background:#4a57a8}}
.run-btn:disabled{{background:#333;color:#666;cursor:default}}
.container{{max-width:940px;margin:0 auto;padding:24px 16px}}
.card{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:12px;padding:20px;margin-bottom:20px}}
.card-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px}}
.date{{font-size:16px;font-weight:700;color:#fff}}
.count{{font-size:12px;color:#888;background:#252836;padding:4px 10px;border-radius:20px}}
.summary{{color:#bbb;font-size:14px;line-height:1.6;margin-bottom:12px}}
.priority{{background:#1e2a1e;border-left:3px solid #4caf50;padding:8px 12px;border-radius:4px;font-size:13px;color:#81c784;margin-bottom:16px}}
h3{{font-size:12px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.5px;margin:16px 0 8px}}
.issue{{background:#12151f;border:1px solid #2a2d3a;border-radius:8px;padding:12px;margin-bottom:8px}}
.issue-header{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap}}
.badge{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:10px;color:#fff}}
.issue-type{{font-size:11px;color:#888;text-transform:capitalize}}
.issue p{{font-size:13px;color:#bbb;line-height:1.5;margin-bottom:4px}}
blockquote{{border-left:2px solid #444;padding-left:10px;font-size:12px;color:#888;font-style:italic;margin:6px 0}}
.win{{font-size:13px;color:#c8e6c9;padding:6px 0;border-bottom:1px solid #1e2a1e}}
.win:last-child{{border-bottom:none}}
/* Fix cards */
.fix-card{{background:#0e1420;border:1px solid #2a3a5a;border-radius:8px;padding:14px;margin-bottom:10px}}
.fix-card.fix-applied{{border-color:#2a5c2a;background:#0e180e}}
.fix-header{{display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap}}
.fix-type-badge{{font-size:10px;font-weight:700;background:#1e3a5f;color:#90caf9;padding:2px 8px;border-radius:10px;text-transform:capitalize}}
.fix-target{{font-size:11px;color:#888}}
.applied-badge{{font-size:10px;background:#1e3a1e;color:#81c784;padding:2px 8px;border-radius:10px;margin-left:auto}}
.fix-desc{{font-size:13px;color:#bbb;margin-bottom:10px;line-height:1.5}}
.fix-preview{{margin-bottom:10px}}
.fix-preview summary{{font-size:12px;color:#666;cursor:pointer;padding:4px 0}}
.fix-preview summary:hover{{color:#90caf9}}
.fix-content{{font-size:11px;color:#aaa;background:#0a0d14;border:1px solid #1e2a3a;border-radius:4px;padding:10px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;max-height:300px;overflow-y:auto;margin-top:6px}}
.diff-block{{font-family:'Fira Mono','Courier New',monospace;font-size:11px;border:1px solid #1e2a3a;border-radius:4px;overflow-y:auto;max-height:400px;margin-top:6px;line-height:1.5}}
.dl-add{{background:#0d2112;color:#a5d6a7;padding:1px 6px;white-space:pre-wrap;word-break:break-word}}
.dl-del{{background:#2d0f0f;color:#ef9a9a;padding:1px 6px;white-space:pre-wrap;word-break:break-word;text-decoration:line-through;opacity:.8}}
.dl-ctx{{background:#0a0d14;color:#555;padding:1px 6px;white-space:pre-wrap;word-break:break-word}}
.dl-gutter{{display:inline-block;width:16px;opacity:.6;user-select:none}}
.fix-actions{{display:flex;gap:8px}}
.apply-btn{{background:#1e3a5f;color:#90caf9;border:1px solid #2a5a8f;border-radius:6px;padding:7px 14px;font-size:12px;font-weight:600;cursor:pointer;transition:background .15s}}
.apply-btn:hover:not([disabled]){{background:#2a5a8f}}
.apply-btn:disabled{{cursor:default}}
.undo-btn{{background:#1a1a1a;color:#888;border:1px solid #333;border-radius:6px;padding:7px 12px;font-size:12px;cursor:pointer}}
.undo-btn:hover:not([disabled]){{background:#2a2a2a;color:#ccc}}
.undo-btn:disabled{{cursor:default}}
.empty{{text-align:center;color:#666;padding:60px 0;font-size:14px}}
#toast{{position:fixed;bottom:20px;right:20px;background:#333;color:#fff;padding:10px 18px;border-radius:8px;font-size:13px;display:none;z-index:999}}
</style>
</head>
<body>
<div class="topbar">
  <h1>🔍 System Observations</h1>
  <div class="topbar-right">
    <a href="/coachobservations">👁 Coach Obs</a>
    <a href="/dashboard">← Dashboard</a>
    <button class="run-btn" id="run-btn" onclick="runNow()">Run Now</button>
  </div>
</div>
<div class="container">{cards}</div>
<div id="toast"></div>
<script>
async function runNow() {{
  const btn = document.getElementById('run-btn');
  btn.disabled = true; btn.textContent = 'Analysing…';
  try {{
    const res = await fetch('/sysobservations/run', {{method:'POST'}});
    const d   = await res.json();
    toast(d.ok ? 'Done — refresh to see results' : (d.error || 'Failed'));
  }} catch(e) {{ toast('Error: ' + e.message); }}
  finally {{ btn.disabled = false; btn.textContent = 'Run Now'; }}
}}

async function applyFix(obsId, fixIdx, btn) {{
  btn.disabled = true; btn.textContent = 'Applying…';
  try {{
    const res = await fetch(`/sysobservations/apply/${{obsId}}/${{fixIdx}}`, {{method:'POST'}});
    const d   = await res.json();
    if (d.ok) {{
      toast('✓ ' + d.message);
      btn.textContent = '✓ Applied';
      btn.style.background = '#2a5c2a';
      const card = btn.closest('.fix-card');
      card.classList.add('fix-applied');
      const undoBtn = card.querySelector('.undo-btn');
      if (undoBtn) {{ undoBtn.disabled = false; undoBtn.style.opacity = '1'; }}
    }} else {{
      toast('Error: ' + (d.error || 'Failed'), true);
      btn.disabled = false; btn.textContent = '⚡ Apply Fix';
    }}
  }} catch(e) {{ toast('Error: ' + e.message, true); btn.disabled = false; btn.textContent = '⚡ Apply Fix'; }}
}}

async function undoFix(obsId, fixIdx, btn) {{
  if (!confirm('Undo this fix? The previous prompt will be restored.')) return;
  btn.disabled = true; btn.textContent = 'Undoing…';
  try {{
    const res = await fetch(`/sysobservations/undo/${{obsId}}/${{fixIdx}}`, {{method:'POST'}});
    const d   = await res.json();
    if (d.ok) {{
      toast('↩ Fix undone');
      const card = btn.closest('.fix-card');
      card.classList.remove('fix-applied');
      const applyBtn = card.querySelector('.apply-btn');
      if (applyBtn) {{ applyBtn.disabled = false; applyBtn.style.background = ''; applyBtn.textContent = '⚡ Apply Fix'; }}
      btn.disabled = true; btn.style.opacity = '.3';
    }} else {{
      toast('Error: ' + (d.error || 'Failed'), true);
      btn.disabled = false; btn.textContent = '↩ Undo';
    }}
  }} catch(e) {{ toast('Error: ' + e.message, true); btn.disabled = false; btn.textContent = '↩ Undo'; }}
}}

function toast(msg, isErr) {{
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.background = isErr ? '#5c1a1a' : '#1a3a1a';
  el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 4000);
}}
</script>
</body>
</html>""")


@router.post("/sysobservations/run")
async def run_watcher_now():
    try:
        await run_system_watcher()
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
