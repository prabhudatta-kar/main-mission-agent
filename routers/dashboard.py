import asyncio
import json
from datetime import date, timedelta
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List

from integrations.firebase_db import sheets
from integrations.whatsapp import whatsapp
from integrations.llm import llm

router = APIRouter(prefix="/dashboard")


def _extract_json(raw: str):
    """Robustly extract JSON from an LLM response that may have markdown fences or extra text."""
    import re
    if not raw:
        return None
    clean = re.sub(r'^```(?:json)?\s*', '', raw.strip())
    clean = re.sub(r'\s*```$', '', clean).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    for sc, ec in [('[', ']'), ('{', '}')]:
        s, e = clean.find(sc), clean.rfind(ec)
        if s != -1 and e > s:
            try:
                return json.loads(clean[s:e + 1])
            except json.JSONDecodeError:
                continue
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status(plan) -> str:
    if not plan:                                      return "no_plan"
    if str(plan.get("day_type","")).lower()=="rest":  return "rest"
    if str(plan.get("completed","")).upper()=="TRUE": return "completed"
    if plan.get("flags"):                             return "flagged"
    if plan.get("runner_feedback"):                   return "completed"
    if str(plan.get("sent","")).upper()=="TRUE":      return "pending"
    return "pending"

def _weeks(race_date_str: str) -> str:
    if not race_date_str: return "—"
    try:
        d = date.fromisoformat(str(race_date_str))
        days = (d - date.today()).days
        if days < 0:   return "Race passed"
        if days <= 7:  return f"Race week ({days}d)"
        return f"{days // 7}w"
    except Exception: return "—"


# ── API endpoints ─────────────────────────────────────────────────────────────

@router.get("/api/data")
async def api_data():
    """Single call that powers the whole dashboard table."""
    coaches = sheets.get_all_active_coaches()
    runners = sheets.get_all_active_runners()
    plans   = sheets.get_all_todays_plans()
    msgs    = sheets.get_all_recent_messages(n=1)

    rows = []
    for r in runners:
        rid  = r["runner_id"]
        plan = plans.get(rid)
        last = msgs.get(rid, [{}])[-1] if msgs.get(rid) else {}
        rows.append({
            "runner_id":   rid,
            "name":        r.get("name",""),
            "phone":       r.get("phone",""),
            "coach_id":    r.get("coach_id",""),
            "race_goal":   r.get("race_goal",""),
            "race_date":   r.get("race_date",""),
            "weeks":       _weeks(r.get("race_date","")),
            "fitness":     r.get("fitness_level",""),
            "injuries":    r.get("injuries","None"),
            "status":      _status(plan),
            "session":     plan.get("session_type","") if plan else "",
            "distance":    plan.get("distance_km","") if plan else "",
            "feedback":    plan.get("runner_feedback","") if plan else "",
            "flags":       plan.get("flags","") if plan else "",
            "last_msg":    last.get("message","")[:80] if last else "",
            "last_dir":    last.get("direction","") if last else "",
        })

    return {
        "today": date.today().isoformat(),
        "coaches": [{"id": c["coach_id"], "name": c.get("coach_name","")} for c in coaches],
        "runners": rows,
    }


@router.get("/api/runner/{runner_id}")
async def api_runner_detail(runner_id: str):
    """Full runner profile + today's plan + conversation history."""
    runner = sheets.get_runner(runner_id)
    if not runner:
        return JSONResponse({"error": "Runner not found"}, status_code=404)
    plan  = sheets.get_todays_plan(runner_id)
    msgs  = sheets.get_last_n_messages(runner_id, n=30)
    rules = sheets.get_active_rules(runner.get("coach_id",""))
    coach_rules = [r for r in rules if r.get("source") in ("coach_instruction","coach_dashboard")]

    return {
        "runner":       runner,
        "plan":         plan,
        "conversations": msgs,
        "coach_notes":  coach_rules,
        "weeks":        _weeks(runner.get("race_date","")),
    }


class MessageReq(BaseModel):
    runner_id: str
    message:   str

@router.post("/api/message")
async def api_send_message(req: MessageReq):
    """Coach sends a direct WhatsApp message — bypasses AI, logged as coach."""
    runner = sheets.get_runner(req.runner_id)
    if not runner:
        return JSONResponse({"error": "Runner not found"}, status_code=404)
    await whatsapp.send_text(runner["phone"], req.message)
    sheets.log_conversation(
        req.runner_id, runner.get("coach_id",""),
        inbound="",  outbound=req.message, intent="coach_direct"
    )
    return {"ok": True}


class NoteReq(BaseModel):
    coach_id:  str
    runner_id: str
    note:      str

@router.post("/api/note")
async def api_add_note(req: NoteReq):
    """Add a coach instruction — agent picks it up from next message."""
    rule = f"For runner {req.runner_id}: {req.note}"
    sheets.add_rule(req.coach_id, rule, source="coach_dashboard", raw_message=req.note)
    return {"ok": True}


class CompleteReq(BaseModel):
    runner_id: str
    distance:  str

@router.post("/api/complete")
async def api_mark_complete(req: CompleteReq):
    plan = sheets.get_todays_plan(req.runner_id)
    if not plan:
        return JSONResponse({"error": "No plan for today"}, status_code=404)
    plan_id = plan.get("plan_id") or plan.get("_id", "")
    if plan_id:
        sheets.update_plan(plan_id, {"completed": "TRUE", "actual_distance": req.distance})
    return {"ok": True}


# ── Plan management endpoints ─────────────────────────────────────────────────

@router.get("/api/runner/{runner_id}/plans")
async def api_runner_plans(runner_id: str, days: int = 30):
    from_date = date.today().isoformat()
    to_date   = (date.today() + timedelta(days=days)).isoformat()
    plans = sheets.get_runner_plans(runner_id, from_date=from_date, to_date=to_date)
    return {"plans": plans}


class GenerateReq(BaseModel):
    weeks:      int = 4
    start_date: str = ""
    notes:      str = ""

@router.post("/api/runner/{runner_id}/plans/generate")
async def api_generate_plan(runner_id: str, req: GenerateReq):
    """Ask the LLM to create a full training plan. Returns JSON for coach review — nothing is saved yet."""
    runner = sheets.get_runner(runner_id)
    if not runner:
        return JSONResponse({"error": "Runner not found"}, status_code=404)

    start = req.start_date or (date.today() + timedelta(days=1)).isoformat()
    end   = (date.fromisoformat(start) + timedelta(weeks=req.weeks)).isoformat()

    race_date = runner.get("race_date", "")
    try:
        weeks_to_race = max(0, (date.fromisoformat(race_date) - date.today()).days // 7) if race_date else "unknown"
    except Exception:
        weeks_to_race = "unknown"

    prompt = f"""You are an expert running coach. Create a {req.weeks}-week training plan.

Runner profile:
- Name: {runner.get('name')}
- Fitness level: {runner.get('fitness_level', 'Intermediate')}
- Race goal: {runner.get('race_goal', 'Unknown')}
- Race date: {race_date} ({weeks_to_race} weeks away)
- Training days per week: {runner.get('weekly_days', 4)}
- Known injuries: {runner.get('injuries', 'None')}
- Coach notes: {runner.get('notes', 'None')}
- Plan period: {start} to {end}

Additional coach instructions: {req.notes or 'None'}

Training principles:
- Max 10% mileage increase per week
- Include one long run per week (Saturday or Sunday)
- Hard/easy alternation — never two hard sessions back to back
- Include 1-2 rest days per week
- Taper the final 1-2 weeks before race
- Session types: Easy Run, Tempo Run, Interval Training, Long Run, Recovery Run, Cross Training, Rest

Return ONLY a JSON array. Each element:
{{
  "date": "YYYY-MM-DD",
  "day_type": "Run|Rest|Cross-train",
  "session_type": "Easy Run|Tempo Run|Interval Training|Long Run|Recovery Run|Cross Training|Rest",
  "distance_km": number (0 for rest/cross-train),
  "intensity": "Zone 2|Threshold|VO2 Max|Easy|Rest",
  "rpe_target": "3-4|4-5|5-6|6-7|7-8|8-9",
  "coach_notes": "specific instruction for this session"
}}

Include every day from {start} to {end}. Training days should have sessions; non-training days should be Rest with distance_km 0."""

    raw = await llm.complete([
        {"role": "system", "content": "You generate structured running training plans. Return only a valid JSON array. No markdown, no explanation, just the JSON array."},
        {"role": "user",   "content": prompt},
    ], model="gpt-4o", max_tokens=4000)

    sessions = _extract_json(raw)
    if sessions is None:
        logger.error(f"Plan generation malformed JSON. Raw response (first 300): {raw[:300]}")
        return JSONResponse({"error": "AI returned malformed JSON. Try again."}, status_code=500)

    return {"sessions": sessions, "runner_id": runner_id}


class PlanEntry(BaseModel):
    runner_id:    str
    date:         str
    day_type:     str = "Run"
    session_type: str = "Easy Run"
    distance_km:  str = ""
    intensity:    str = "Zone 2"
    rpe_target:   str = "4-5"
    coach_notes:  str = ""

@router.post("/api/plan")
async def api_create_plan(req: PlanEntry):
    plan_id = sheets.create_plan(req.dict())
    return {"ok": True, "plan_id": plan_id}


class BulkPlansReq(BaseModel):
    runner_id:    str
    sessions:     List[dict]
    delete_first: bool = False  # if True, wipe all future plans before saving

@router.post("/api/plans/bulk")
async def api_bulk_save(req: BulkPlansReq):
    """Save multiple plan entries. delete_first=True clears all future sessions first."""
    deleted = 0
    if req.delete_first:
        from_date = date.today().isoformat()
        deleted   = sheets.delete_all_runner_plans(req.runner_id, from_date=from_date)

    saved = 0
    for s in req.sessions:
        s["runner_id"] = req.runner_id
        sheets.create_plan(s)
        saved += 1
    return {"ok": True, "saved": saved, "deleted": deleted}


class PlanUpdateReq(BaseModel):
    session_type: str = ""
    distance_km:  str = ""
    intensity:    str = ""
    rpe_target:   str = ""
    coach_notes:  str = ""
    day_type:     str = ""

@router.put("/api/plan/{plan_id}")
async def api_update_plan(plan_id: str, req: PlanUpdateReq):
    fields = {k: v for k, v in req.dict().items() if v}
    sheets.update_plan(plan_id, fields)
    return {"ok": True}


@router.delete("/api/plan/{plan_id}")
async def api_delete_plan(plan_id: str):
    sheets.delete_plan(plan_id)
    return {"ok": True}


class PlanChatReq(BaseModel):
    message:  str
    history:  List[dict] = []

@router.post("/api/runner/{runner_id}/plan/chat")
async def api_plan_chat(runner_id: str, req: PlanChatReq):
    """AI assistant for creating and editing training plans via natural language."""
    runner = sheets.get_runner(runner_id)
    if not runner:
        return JSONResponse({"error": "Runner not found"}, status_code=404)

    # Load existing upcoming plans for context
    from_date = date.today().isoformat()
    to_date   = (date.today() + timedelta(days=84)).isoformat()
    existing  = sheets.get_runner_plans(runner_id, from_date=from_date, to_date=to_date)
    plan_summary = "\n".join(
        f"- {p['date']}: {p.get('session_type','')} {p.get('distance_km','')}km"
        for p in existing[:20]
    ) or "No upcoming sessions yet."

    race_date = runner.get("race_date", "")
    try:
        weeks_out = max(0, (date.fromisoformat(race_date) - date.today()).days // 7) if race_date else "?"
    except Exception:
        weeks_out = "?"

    system = f"""You are an expert running coach AI helping manage training plans.

Runner: {runner.get('name')}, {runner.get('fitness_level','Intermediate')} level
Race: {runner.get('race_goal','Unknown')} on {race_date} ({weeks_out} weeks away)
Training days/week: {runner.get('weekly_days',4)}
Injuries: {runner.get('injuries','None')}
Coach notes: {runner.get('notes','')}

Existing upcoming sessions:
{plan_summary}

Respond ONLY with a JSON object (no markdown fences):
{{
  "message": "Conversational reply explaining your plan and reasoning",
  "action": "create_sessions|replace_sessions|no_sessions",
  "sessions": [
    {{
      "date": "YYYY-MM-DD",
      "day_type": "Run|Rest|Cross-train",
      "session_type": "Easy Run|Tempo Run|Interval Training|Long Run|Recovery Run|Cross Training|Rest",
      "distance_km": number,
      "intensity": "Zone 2|Threshold|VO2 Max|Easy|Rest",
      "rpe_target": "4-5",
      "coach_notes": "specific instruction for this session"
    }}
  ]
}}

Action meanings:
- "create_sessions": Add new sessions, keeping any existing ones
- "replace_sessions": DELETE all existing future sessions for this runner, then create these new ones. Use when the coach asks to start fresh, delete everything, or completely redo the plan.
- "no_sessions": No plan changes needed (info / question response)

Always explain your reasoning in message. Be specific about dates and session rationale."""

    messages = [{"role": "system", "content": system}]
    for h in req.history[-6:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": req.message})

    raw = await llm.complete(messages, model="gpt-4o", max_tokens=4000)

    result = _extract_json(raw)
    if result is None or not isinstance(result, dict):
        result = {"message": raw, "action": "no_sessions", "sessions": []}

    return result


# ── AI management endpoints ───────────────────────────────────────────────────

@router.get("/api/coach/{coach_id}/config")
async def api_coach_config(coach_id: str):
    config = sheets.get_coach_config(coach_id)
    if not config:
        return JSONResponse({"error": "Coach not found"}, status_code=404)
    # Build version history from flat fields
    versions = []
    for i in range(1, 20):
        key = f"system_prompt_v{i}"
        if key not in config:
            break
        versions.append({
            "version": f"v{i}",
            "date":    config.get(f"system_prompt_v{i}_date", ""),
            "active":  config.get("active_prompt_version") == f"v{i}",
            "preview": (config.get(key) or "")[:100],
        })
    return {
        "coach_id":      coach_id,
        "coach_name":    config.get("coach_name", ""),
        "active_version": config.get("active_prompt_version", "v1"),
        "active_prompt": config.get("active_system_prompt", ""),
        "versions":      list(reversed(versions)),  # newest first
    }


class PromptUpdateReq(BaseModel):
    prompt: str

@router.post("/api/coach/{coach_id}/prompt")
async def api_update_prompt(coach_id: str, req: PromptUpdateReq):
    new_version = sheets.update_coach_prompt(coach_id, req.prompt.strip())
    return {"ok": True, "version": new_version}


@router.post("/api/coach/{coach_id}/prompt/restore/{version}")
async def api_restore_prompt(coach_id: str, version: str):
    sheets.restore_prompt_version(coach_id, version)
    return {"ok": True}


@router.get("/api/coach/{coach_id}/rules")
async def api_coach_rules(coach_id: str):
    rules = sheets.get_all_coach_rules(coach_id)
    return {"rules": rules}


class RuleReq(BaseModel):
    rule: str

@router.post("/api/coach/{coach_id}/rule")
async def api_add_rule(coach_id: str, req: RuleReq):
    sheets.add_rule(coach_id, req.rule.strip(), source="coach_manual")
    return {"ok": True}


@router.put("/api/rule/{rule_id}/archive")
async def api_archive_rule(rule_id: str):
    sheets.archive_rule(rule_id)
    return {"ok": True}


@router.put("/api/rule/{rule_id}/restore")
async def api_restore_rule(rule_id: str):
    sheets.restore_rule(rule_id)
    return {"ok": True}


@router.delete("/api/rule/{rule_id}")
async def api_delete_rule(rule_id: str):
    sheets.delete_rule(rule_id)
    return {"ok": True}


# ── HTML page ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(_HTML)


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Main Mission — Coach Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#1a1a2e;height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* Header */
header{background:#1a1a2e;color:#fff;padding:14px 24px;display:flex;align-items:center;gap:12px;flex-shrink:0;z-index:10}
header h1{font-size:18px;font-weight:700;flex:1}
.hdr-meta{font-size:12px;color:#8696a0;display:flex;align-items:center;gap:16px}
.refresh-btn{background:#00a884;border:none;color:#fff;padding:6px 14px;border-radius:20px;font-size:12px;cursor:pointer;font-weight:600}
.refresh-btn:hover{background:#008c6e}
.manage-ai-btn{background:#7c3aed;border:none;color:#fff;padding:6px 14px;border-radius:20px;font-size:12px;cursor:pointer;font-weight:600}
.manage-ai-btn:hover{background:#6d28d9}

/* Manage AI modal */
.mai-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:300;display:flex;align-items:center;justify-content:center;padding:20px}
.mai-modal{background:#fff;border-radius:14px;width:92vw;max-width:1100px;height:88vh;display:flex;flex-direction:column;box-shadow:0 24px 80px rgba(0,0,0,.25)}
.mai-hdr{padding:18px 24px;border-bottom:1px solid #eee;display:flex;align-items:center;gap:12px;flex-shrink:0}
.mai-hdr h2{font-size:18px;flex:1}
.mai-tabs{display:flex;border-bottom:1px solid #eee;flex-shrink:0}
.mai-tab{padding:12px 24px;font-size:13px;font-weight:600;cursor:pointer;color:#666;border-bottom:2px solid transparent;transition:all .15s}
.mai-tab.active{color:#7c3aed;border-bottom-color:#7c3aed}
.mai-body{flex:1;overflow:hidden;display:flex;flex-direction:column}
.mai-pane{display:none;flex:1;overflow-y:auto;padding:24px}
.mai-pane.active{display:flex;flex-direction:column;gap:16px}
.mai-ftr{padding:14px 24px;border-top:1px solid #eee;display:flex;gap:8px;justify-content:flex-end;flex-shrink:0}

/* Prompt editor */
.prompt-editor{width:100%;border:1px solid #ddd;border-radius:10px;padding:14px;font-size:13px;font-family:inherit;resize:vertical;min-height:300px;line-height:1.6;outline:none}
.prompt-editor:focus{border-color:#7c3aed}
.version-table{width:100%;border-collapse:collapse;font-size:13px}
.version-table th{padding:8px 12px;background:#f9f9f9;font-weight:600;color:#555;text-align:left;border-bottom:1px solid #eee}
.version-table td{padding:8px 12px;border-bottom:1px solid #f5f5f5;vertical-align:middle}
.ver-active{display:inline-block;background:#dcfce7;color:#166534;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.ver-old{display:inline-block;background:#f3f4f6;color:#555;padding:2px 8px;border-radius:10px;font-size:11px}
.ver-preview{color:#aaa;font-size:12px;font-style:italic;max-width:400px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* Rules list */
.rule-add-form{display:flex;gap:8px;margin-bottom:8px}
.rule-add-input{flex:1;border:1px solid #ddd;border-radius:8px;padding:10px 14px;font-size:13px;outline:none;font-family:inherit}
.rule-add-input:focus{border-color:#7c3aed}
.rules-table{width:100%;border-collapse:collapse;font-size:13px}
.rules-table th{padding:8px 12px;background:#f9f9f9;font-weight:600;color:#555;text-align:left;border-bottom:1px solid #eee;white-space:nowrap}
.rules-table td{padding:10px 12px;border-bottom:1px solid #f5f5f5;vertical-align:top}
.rules-table tr.archived td{opacity:.45}
.source-badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap}
.src-correction{background:#fee2e2;color:#991b1b}
.src-instruction{background:#dbeafe;color:#1e40af}
.src-manual{background:#f0fdf4;color:#166534}
.src-dashboard{background:#faf5ff;color:#6b21a8}
.src-other{background:#f3f4f6;color:#374151}
.rule-actions{display:flex;gap:4px;flex-shrink:0}

/* Layout */
.layout{display:flex;flex:1;overflow:hidden}
.main{flex:1;overflow-y:auto;padding:20px 24px;transition:width .3s}
.panel{width:0;overflow:hidden;background:#fff;border-left:1px solid #e5e7eb;flex-shrink:0;display:flex;flex-direction:row;min-width:0}
.panel.open{width:440px}
.drag-handle{width:6px;cursor:col-resize;background:transparent;flex-shrink:0;position:relative;z-index:10}
.drag-handle:hover,.drag-handle.dragging{background:linear-gradient(to right,#d1fae5,#00a884)}
.drag-handle::after{content:'⋮';position:absolute;left:-2px;top:50%;transform:translateY(-50%);color:#ccc;font-size:14px;line-height:1}
.drag-handle:hover::after,.drag-handle.dragging::after{color:#00a884}
.panel-inner{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}

/* Summary tiles */
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}
.tile{background:#fff;border-radius:12px;padding:16px 20px;cursor:pointer;border:2px solid transparent;box-shadow:0 1px 3px rgba(0,0,0,.07);transition:all .15s}
.tile:hover{border-color:#00a884;transform:translateY(-1px)}
.tile.active{border-color:#00a884;background:#f0fdf9}
.tile .num{font-size:30px;font-weight:700;line-height:1}
.tile .lbl{font-size:12px;color:#666;margin-top:4px}
.tile.c-blue .num{color:#1976d2}
.tile.c-green .num{color:#00a884}
.tile.c-amber .num{color:#f59e0b}
.tile.c-red .num{color:#e53935}
.tile.c-purple .num{color:#7c3aed}

/* Escalation alert */
.alert-bar{background:#fff3cd;border:1px solid #ffc107;border-radius:10px;padding:10px 16px;margin-bottom:16px;display:flex;align-items:center;gap:10px;font-size:13px}
.alert-bar .alert-icon{font-size:18px}
.alert-bar strong{color:#856404}
.alert-names{color:#333;flex:1}

/* Toolbar */
.toolbar{display:flex;gap:10px;margin-bottom:14px;align-items:center}
.search-box{flex:1;padding:8px 14px;border:1px solid #ddd;border-radius:8px;font-size:14px;outline:none}
.search-box:focus{border-color:#00a884}
select.filter{padding:8px 12px;border:1px solid #ddd;border-radius:8px;font-size:13px;outline:none;background:#fff;cursor:pointer}

/* Table */
.table-wrap{background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.07);overflow:hidden}
table{width:100%;border-collapse:collapse}
th{padding:10px 14px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:#666;background:#fafafa;border-bottom:1px solid #eee;text-align:left;white-space:nowrap}
td{padding:11px 14px;font-size:13px;border-bottom:1px solid #f5f5f5;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr.runner-row{cursor:pointer;transition:background .1s}
tr.runner-row:hover td{background:#f8fffe}
tr.runner-row.selected td{background:#f0fdf9}
td small{display:block;font-size:11px;color:#999;margin-top:2px}
.avatar{width:32px;height:32px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#fff;flex-shrink:0}
.name-cell{display:flex;align-items:center;gap:10px}
.badge{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap}
.s-completed{background:#dcfce7;color:#166534}
.s-pending{background:#fef9c3;color:#854d0e}
.s-flagged{background:#fee2e2;color:#991b1b}
.s-rest{background:#dbeafe;color:#1e40af}
.s-no_plan{background:#f3f4f6;color:#6b7280}
.act-btn{background:none;border:1px solid #e5e7eb;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:12px;color:#555;transition:all .1s}
.act-btn:hover{border-color:#00a884;color:#00a884}
.no-data{text-align:center;padding:40px;color:#aaa}

/* Side panel */
.panel-header{padding:16px 20px;border-bottom:1px solid #eee;display:flex;align-items:flex-start;gap:12px;flex-shrink:0}
.panel-avatar{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;color:#fff;flex-shrink:0}
.panel-name{font-size:16px;font-weight:700}
.panel-sub{font-size:12px;color:#666;margin-top:2px}
.close-btn{margin-left:auto;background:none;border:none;font-size:20px;cursor:pointer;color:#999;padding:6px 10px;border-radius:6px;line-height:1}
.close-btn:hover{background:#f3f4f6;color:#555}
.panel-tabs{display:flex;border-bottom:1px solid #eee;flex-shrink:0}
.tab{flex:1;padding:10px;font-size:12px;font-weight:600;text-align:center;cursor:pointer;color:#666;border-bottom:2px solid transparent;transition:all .15s}
.tab.active{color:#00a884;border-bottom-color:#00a884}
.panel-body{flex:1;overflow-y:auto;padding:16px}
.tab-pane{display:none}
.tab-pane.active{display:block}

/* Panel — profile */
.profile-row{display:flex;justify-content:space-between;margin-bottom:10px;font-size:13px}
.profile-row .lbl{color:#666}
.profile-row .val{font-weight:600;text-align:right;max-width:60%}
.injury-tag{background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.plan-card{background:#f8fffe;border:1px solid #d1fae5;border-radius:10px;padding:12px 14px;margin-bottom:12px;font-size:13px}
.plan-card .plan-title{font-weight:700;font-size:14px;margin-bottom:6px}
.plan-card .plan-row{color:#666;margin-top:3px}
.plan-card .plan-notes{margin-top:8px;font-size:12px;color:#444;background:#fff;border-radius:6px;padding:8px 10px;line-height:1.5}
.feedback-card{background:#f0fdf9;border-radius:8px;padding:10px 12px;font-size:13px;color:#166534;margin-top:8px}

/* Panel — conversations */
.conv-list{display:flex;flex-direction:column;gap:8px}
.bubble{max-width:85%;padding:8px 12px;border-radius:12px;font-size:13px;line-height:1.4}
.bubble.in{align-self:flex-start;background:#f3f4f6;border-bottom-left-radius:3px}
.bubble.out{align-self:flex-end;background:#dcfce7;border-bottom-right-radius:3px;text-align:right}
.bubble .ts{font-size:10px;color:#999;margin-top:4px}

/* Panel — compose */
.compose-area{border-top:1px solid #eee;padding:14px 16px;flex-shrink:0;background:#fff}
.compose-area label{font-size:11px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.05em;display:block;margin-bottom:6px}
.compose-textarea{width:100%;border:1px solid #ddd;border-radius:8px;padding:10px 12px;font-size:13px;resize:none;outline:none;font-family:inherit;min-height:72px}
.compose-textarea:focus{border-color:#00a884}
.compose-actions{display:flex;gap:8px;margin-top:8px}
.send-btn{background:#00a884;color:#fff;border:none;border-radius:8px;padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;flex:1}
.send-btn:hover{background:#008c6e}
.send-btn:disabled{background:#ccc;cursor:default}
.note-btn{background:#7c3aed;color:#fff;border:none;border-radius:8px;padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;flex:1}
.note-btn:hover{background:#6d28d9}

/* Toast */
.toast{position:fixed;bottom:24px;right:24px;background:#1a1a2e;color:#fff;padding:12px 20px;border-radius:10px;font-size:13px;opacity:0;transform:translateY(12px);transition:all .3s;z-index:1000;pointer-events:none}
.toast.show{opacity:1;transform:translateY(0)}
.toast.error{background:#e53935}

/* Loading */
.loading{text-align:center;padding:40px;color:#aaa;font-size:14px}

/* Plan tab */
.plan-toolbar{display:flex;gap:8px;margin-bottom:14px}
.plan-toolbar button{padding:6px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;border:none}
.btn-generate{background:#7c3aed;color:#fff}.btn-generate:hover{background:#6d28d9}
.btn-add{background:#00a884;color:#fff}.btn-add:hover{background:#008c6e}
.session-list{display:flex;flex-direction:column;gap:6px}
.session-card{border-radius:8px;padding:10px 12px;display:flex;align-items:flex-start;gap:10px;position:relative;font-size:13px}
.sc-easy{background:#f0fdf4;border-left:3px solid #22c55e}
.sc-tempo{background:#fff7ed;border-left:3px solid #f97316}
.sc-interval{background:#fef2f2;border-left:3px solid #ef4444}
.sc-long{background:#faf5ff;border-left:3px solid #a855f7}
.sc-recovery{background:#f0fdf4;border-left:3px solid #86efac}
.sc-rest{background:#f9fafb;border-left:3px solid #d1d5db;color:#9ca3af}
.sc-cross{background:#eff6ff;border-left:3px solid #60a5fa}
.sc-date{font-size:11px;font-weight:700;color:#666;min-width:60px;flex-shrink:0;padding-top:2px}
.sc-body{flex:1}
.sc-title{font-weight:700}
.sc-meta{font-size:11px;color:#666;margin-top:2px}
.sc-notes{font-size:11px;color:#555;margin-top:4px;line-height:1.4}
.sc-actions{display:flex;gap:4px;opacity:0;transition:opacity .15s}
.session-card:hover .sc-actions{opacity:1}
.sc-btn{background:none;border:1px solid #e5e7eb;border-radius:4px;padding:2px 6px;font-size:11px;cursor:pointer;color:#555}
.sc-btn:hover{border-color:#00a884;color:#00a884}
.sc-btn.del:hover{border-color:#e53935;color:#e53935}
.week-header{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:#aaa;margin:12px 0 6px;padding-bottom:4px;border-bottom:1px solid #eee}

/* Generate modal overlay */
.gen-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:200;display:flex;align-items:center;justify-content:center;padding:20px}
.gen-modal{background:#fff;border-radius:14px;width:92vw;max-width:1200px;height:88vh;display:flex;flex-direction:column;box-shadow:0 24px 80px rgba(0,0,0,.25)}
.gen-modal-hdr{padding:18px 24px;border-bottom:1px solid #eee;display:flex;align-items:center;gap:10px;flex-shrink:0}
.gen-modal-hdr h2{font-size:16px;flex:1}
.gen-modal-body{padding:18px 24px;overflow-y:auto;overflow-x:hidden;flex:1}
.gen-modal-ftr{padding:14px 24px;border-top:1px solid #eee;display:flex;gap:8px;justify-content:flex-end;flex-shrink:0}
.form-row{margin-bottom:12px}
.form-row label{font-size:12px;font-weight:600;color:#555;display:block;margin-bottom:4px}
.form-row input,.form-row select,.form-row textarea{width:100%;border:1px solid #ddd;border-radius:8px;padding:8px 10px;font-size:13px;outline:none;font-family:inherit}
.form-row input:focus,.form-row select:focus,.form-row textarea:focus{border-color:#00a884}
.preview-wrap{overflow-x:auto;border-radius:8px;border:1px solid #e5e7eb}
.preview-table{width:max-content;min-width:100%;border-collapse:collapse;font-size:12px}
.preview-table th{padding:8px 10px;background:#f5f5f5;text-align:left;font-weight:600;color:#555;border-bottom:1px solid #eee;white-space:nowrap}
.preview-table td{padding:6px 8px;border-bottom:1px solid #f5f5f5;vertical-align:middle;white-space:nowrap}
.preview-table input{border:1px solid transparent;border-radius:4px;padding:3px 6px;font-size:12px;width:100%;min-width:80px;background:transparent}
.preview-table input.wide{min-width:200px}
.preview-table input:focus{border-color:#00a884;background:#fff;outline:none}
.preview-table tr:hover td{background:#fafffe}
.preview-count{font-size:12px;color:#666;margin-bottom:8px}
.btn-primary{background:#00a884;color:#fff;border:none;border-radius:8px;padding:9px 20px;font-size:13px;font-weight:600;cursor:pointer}
.btn-primary:hover{background:#008c6e}
.btn-primary:disabled{background:#ccc;cursor:default}
.btn-secondary{background:#f3f4f6;color:#374151;border:none;border-radius:8px;padding:9px 20px;font-size:13px;font-weight:600;cursor:pointer}
.btn-secondary:hover{background:#e5e7eb}
.btn-purple{background:#7c3aed;color:#fff;border:none;border-radius:8px;padding:9px 20px;font-size:13px;font-weight:600;cursor:pointer}
.btn-purple:hover{background:#6d28d9}
.btn-purple:disabled{background:#ccc;cursor:default}

/* Plan AI chat */
.plan-chat{display:flex;flex-direction:column;gap:8px;margin-bottom:14px}
.pchat-msg{max-width:90%;padding:10px 13px;border-radius:10px;font-size:13px;line-height:1.5}
.pchat-msg.coach{align-self:flex-end;background:#005c4b;color:#fff;border-bottom-right-radius:3px}
.pchat-msg.ai{align-self:flex-start;background:#f0f2f5;color:#1a1a2e;border-bottom-left-radius:3px}
.pchat-msg .pchat-meta{font-size:10px;opacity:.6;margin-top:4px;text-align:right}
.plan-preview-box{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;margin-top:6px;overflow:hidden}
.plan-preview-box table{width:100%;border-collapse:collapse;font-size:11px}
.plan-preview-box th{padding:5px 8px;background:#f3f4f6;font-weight:600;color:#555;text-align:left}
.plan-preview-box td{padding:5px 8px;border-top:1px solid #f0f0f0}
.plan-preview-actions{display:flex;gap:6px;padding:8px 10px;border-top:1px solid #e5e7eb;background:#fafafa}
.compose-ai-label{font-size:11px;font-weight:600;color:#7c3aed;text-transform:uppercase;letter-spacing:.05em;display:block;margin-bottom:6px}
.compose-plan-textarea{width:100%;border:1px solid #c4b5fd;border-radius:8px;padding:10px 12px;font-size:13px;resize:none;outline:none;font-family:inherit;min-height:72px}
.compose-plan-textarea:focus{border-color:#7c3aed}
.ask-ai-btn{background:#7c3aed;color:#fff;border:none;border-radius:8px;padding:8px 18px;font-size:13px;font-weight:600;cursor:pointer;flex:1}
.ask-ai-btn:hover{background:#6d28d9}
.ask-ai-btn:disabled{background:#ccc;cursor:default}

/* Edit session inline form */
.edit-form{background:#f8f9fa;border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-top:6px;font-size:12px}
.edit-form .ef-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}
.edit-form label{font-size:11px;font-weight:600;color:#666;display:block;margin-bottom:2px}
.edit-form input,.edit-form select,.edit-form textarea{width:100%;border:1px solid #ddd;border-radius:6px;padding:5px 8px;font-size:12px;font-family:inherit;outline:none}
.edit-form input:focus,.edit-form select:focus,.edit-form textarea:focus{border-color:#00a884}
.edit-form-actions{display:flex;gap:6px;margin-top:6px}
.ef-save{background:#00a884;color:#fff;border:none;border-radius:6px;padding:5px 14px;font-size:12px;font-weight:600;cursor:pointer}
.ef-cancel{background:#f3f4f6;color:#555;border:none;border-radius:6px;padding:5px 12px;font-size:12px;cursor:pointer}
</style>
</head>
<body>

<header>
  <div>🏃</div>
  <h1>Main Mission — Coach Dashboard</h1>
  <div class="hdr-meta">
    <span id="hdr-date">—</span>
    <button class="manage-ai-btn" onclick="openManageAI()">⚙ Manage AI</button>
    <button class="refresh-btn" onclick="loadData()">↻ Refresh</button>
    <a href="/sysobservations" style="color:#aaa;font-size:12px;text-decoration:none">🔍 Observations</a>
    <a href="/logout" style="color:#888;font-size:12px;text-decoration:none">Sign out</a>
  </div>
</header>

<div class="layout">
  <!-- Main content -->
  <div class="main" id="main">
    <!-- Summary tiles -->
    <div class="tiles">
      <div class="tile c-blue active" onclick="setFilter('all')" id="tile-all">
        <div class="num" id="t-total">—</div><div class="lbl">All runners</div>
      </div>
      <div class="tile c-green" onclick="setFilter('completed')" id="tile-completed">
        <div class="num" id="t-completed">—</div><div class="lbl">Completed today</div>
      </div>
      <div class="tile c-amber" onclick="setFilter('pending')" id="tile-pending">
        <div class="num" id="t-pending">—</div><div class="lbl">Pending / no response</div>
      </div>
      <div class="tile c-red" onclick="setFilter('flagged')" id="tile-flagged">
        <div class="num" id="t-flagged">—</div><div class="lbl">Flagged / injury</div>
      </div>
      <div class="tile c-purple" onclick="setFilter('rest')" id="tile-rest">
        <div class="num" id="t-rest">—</div><div class="lbl">Rest day</div>
      </div>
    </div>

    <!-- Escalation alert bar -->
    <div class="alert-bar" id="alert-bar" style="display:none">
      <div class="alert-icon">⚠️</div>
      <div>
        <strong>Needs attention: </strong>
        <span class="alert-names" id="alert-names"></span>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <input class="search-box" id="search" placeholder="Search runner…" oninput="renderTable()">
      <select class="filter" id="race-filter" onchange="renderTable()">
        <option value="">All races</option>
      </select>
    </div>

    <!-- Table -->
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Runner</th>
            <th>Race goal</th>
            <th>Weeks</th>
            <th>Today's session</th>
            <th>Status</th>
            <th>Last message</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="tbody"><tr><td colspan="7" class="loading">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- Side panel -->
  <div class="panel" id="panel">
    <div class="drag-handle" id="drag-handle"></div>
    <div class="panel-inner">
    <div class="panel-header">
      <div class="panel-avatar" id="p-avatar">—</div>
      <div>
        <div class="panel-name" id="p-name">—</div>
        <div class="panel-sub" id="p-sub">—</div>
      </div>
      <button class="close-btn" onclick="closePanel()">✕</button>
    </div>

    <div class="panel-tabs">
      <div class="tab active" onclick="switchTab('today')">Today</div>
      <div class="tab" onclick="switchTab('history')">History</div>
      <div class="tab" onclick="switchTab('plan')">Plan</div>
      <div class="tab" onclick="switchTab('profile')">Profile</div>
    </div>

    <div class="panel-body">
      <div class="tab-pane active" id="tab-today">
        <div id="today-content"><div class="loading">Loading…</div></div>
      </div>
      <div class="tab-pane" id="tab-history">
        <div class="conv-list" id="conv-list"><div class="loading">Loading…</div></div>
      </div>
      <div class="tab-pane" id="tab-plan">
        <div class="plan-chat" id="plan-chat"></div>
        <div id="plan-content"><div class="loading">Loading…</div></div>
      </div>
      <div class="tab-pane" id="tab-profile">
        <div id="profile-content"><div class="loading">Loading…</div></div>
      </div>
    </div>

    <div class="compose-area" id="compose-area">
      <!-- Swapped by JS based on active tab -->
    </div>
    </div><!-- /panel-inner -->
  </div>
</div>

<div class="toast" id="toast"></div>

<!-- Manage AI Modal -->
<div class="mai-overlay" id="mai-overlay" style="display:none" onclick="if(event.target===this)closeManageAI()">
  <div class="mai-modal">
    <div class="mai-hdr">
      <span style="font-size:22px">🧠</span>
      <h2>Manage AI — <span id="mai-coach-name">Coach</span></h2>
      <button class="close-btn" onclick="closeManageAI()">✕</button>
    </div>
    <div class="mai-tabs">
      <div class="mai-tab active" onclick="switchMAITab('personality')">🧠 AI Personality</div>
      <div class="mai-tab" onclick="switchMAITab('rules')">📋 Rules &amp; Memory</div>
    </div>
    <div class="mai-body">
      <!-- Personality tab -->
      <div class="mai-pane active" id="mai-personality">
        <div>
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
            <strong style="font-size:14px">Active System Prompt</strong>
            <span id="mai-active-ver" class="ver-active">v1</span>
            <span style="font-size:12px;color:#aaa;flex:1">This is the personality and instructions the AI uses for every conversation.</span>
          </div>
          <textarea class="prompt-editor" id="mai-prompt" placeholder="Loading…"></textarea>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn-purple" onclick="savePrompt()">Save as New Version &amp; Activate</button>
          <span style="font-size:12px;color:#aaa;align-self:center">Saving creates a new version and activates it immediately. Old versions are preserved.</span>
        </div>
        <div id="mai-versions">
          <strong style="font-size:13px;color:#555">Version history</strong>
          <table class="version-table" style="margin-top:8px">
            <thead><tr><th>Version</th><th>Date</th><th>Status</th><th>Preview</th><th></th></tr></thead>
            <tbody id="mai-versions-tbody"><tr><td colspan="5" style="color:#aaa;padding:12px">Loading…</td></tr></tbody>
          </table>
        </div>
      </div>

      <!-- Rules tab -->
      <div class="mai-pane" id="mai-rules">
        <div>
          <strong style="font-size:14px">Add new instruction</strong>
          <p style="font-size:12px;color:#666;margin:4px 0 10px">Rules are injected into every AI response. The agent follows them automatically.</p>
          <div class="rule-add-form">
            <input class="rule-add-input" id="mai-new-rule" placeholder="e.g. Always recommend complete rest for knee pain — never suggest modified running"
              onkeydown="if(event.key==='Enter')addRule()">
            <button class="btn-purple" onclick="addRule()">Add Rule</button>
          </div>
        </div>
        <div style="flex:1">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
            <strong style="font-size:14px">All rules</strong>
            <label style="font-size:12px;color:#666;margin-left:auto">
              <input type="checkbox" id="show-archived" onchange="loadRules()"> Show archived
            </label>
          </div>
          <table class="rules-table">
            <thead><tr><th style="width:55%">Rule</th><th>Source</th><th>Added</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody id="mai-rules-tbody"><tr><td colspan="5" style="color:#aaa;padding:16px">Loading…</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="mai-ftr">
      <button class="btn-secondary" onclick="closeManageAI()">Close</button>
    </div>
  </div>
</div>

<!-- Generate Plan Modal -->
<div class="gen-overlay" id="gen-overlay" style="display:none" onclick="if(event.target===this)closeGenModal()">
  <div class="gen-modal">
    <div class="gen-modal-hdr">
      <span style="font-size:20px">🤖</span>
      <h2>Generate Training Plan with AI</h2>
      <button class="close-btn" onclick="closeGenModal()">✕</button>
    </div>
    <div class="gen-modal-body" id="gen-modal-body">
      <div id="gen-form">
        <div class="form-row">
          <label>Weeks to generate</label>
          <select id="gen-weeks">
            <option value="2">2 weeks</option>
            <option value="4" selected>4 weeks</option>
            <option value="6">6 weeks</option>
            <option value="8">8 weeks</option>
            <option value="12">12 weeks</option>
          </select>
        </div>
        <div class="form-row">
          <label>Start date</label>
          <input type="date" id="gen-start" />
        </div>
        <div class="form-row">
          <label>Additional instructions for AI (optional)</label>
          <textarea id="gen-notes" rows="3" placeholder="e.g. Focus on hill training. Runner has a work trip week 3 so reduce to 2 sessions that week."></textarea>
        </div>
      </div>
      <div id="gen-preview" style="display:none">
        <p class="preview-count" id="preview-count"></p>
        <div class="preview-wrap">
          <table class="preview-table" id="preview-table">
            <thead><tr><th>Date</th><th>Day</th><th>Session type</th><th>km</th><th>Intensity</th><th>RPE</th><th>Notes</th><th></th></tr></thead>
            <tbody id="preview-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="gen-modal-ftr" id="gen-modal-ftr">
      <button class="btn-secondary" onclick="closeGenModal()">Cancel</button>
      <button class="btn-purple" id="gen-btn" onclick="generatePlan()">✨ Generate with AI</button>
    </div>
  </div>
</div>

<script>
let allRunners = [];
let coaches    = [];
let activeFilter = 'all';
let activeRunner = null;

// ── Load all data ─────────────────────────────────────────────────────────────

async function loadData() {
  try {
    const res  = await fetch('/dashboard/api/data');
    const data = await res.json();

    document.getElementById('hdr-date').textContent = data.today;
    allRunners = data.runners;
    coaches    = data.coaches;

    // Populate race filter dropdown
    const races = [...new Set(allRunners.map(r => r.race_goal).filter(Boolean))];
    const sel   = document.getElementById('race-filter');
    sel.innerHTML = '<option value="">All races</option>' +
      races.map(r => `<option value="${r}">${r}</option>`).join('');

    updateTiles();
    updateAlertBar();
    renderTable();
  } catch(e) {
    document.getElementById('tbody').innerHTML =
      `<tr><td colspan="7" class="loading" style="color:red">Error loading data: ${e.message}</td></tr>`;
  }
}

// ── Tiles ─────────────────────────────────────────────────────────────────────

function updateTiles() {
  const counts = {all: allRunners.length, completed: 0, pending: 0, flagged: 0, rest: 0};
  allRunners.forEach(r => { if (counts[r.status] !== undefined) counts[r.status]++; });
  document.getElementById('t-total').textContent     = counts.all;
  document.getElementById('t-completed').textContent = counts.completed;
  document.getElementById('t-pending').textContent   = counts.pending;
  document.getElementById('t-flagged').textContent   = counts.flagged;
  document.getElementById('t-rest').textContent      = counts.rest;
}

function setFilter(f) {
  activeFilter = f;
  document.querySelectorAll('.tile').forEach(t => t.classList.remove('active'));
  document.getElementById('tile-' + f)?.classList.add('active');
  renderTable();
}

// ── Alert bar ─────────────────────────────────────────────────────────────────

function updateAlertBar() {
  const flagged = allRunners.filter(r => r.status === 'flagged');
  const bar = document.getElementById('alert-bar');
  if (flagged.length === 0) { bar.style.display = 'none'; return; }
  bar.style.display = 'flex';
  document.getElementById('alert-names').textContent =
    flagged.map(r => `${r.name} (${r.flags || 'flagged'})`).join(' · ');
}

// ── Table ─────────────────────────────────────────────────────────────────────

const STATUS_LABELS = {
  completed: ['Completed', 's-completed'],
  pending:   ['Pending',   's-pending'],
  flagged:   ['⚠ Flagged', 's-flagged'],
  rest:      ['Rest day',  's-rest'],
  no_plan:   ['No plan',   's-no_plan'],
};

function avatarColor(name) {
  const colors = ['#e91e63','#9c27b0','#3f51b5','#03a9f4','#009688','#ff5722','#795548','#607d8b'];
  let h = 0; for(const c of name) h = c.charCodeAt(0) + ((h<<5)-h);
  return colors[Math.abs(h) % colors.length];
}

function initials(name) {
  return name.split(' ').map(p=>p[0]).slice(0,2).join('').toUpperCase();
}

function renderTable() {
  const q     = document.getElementById('search').value.toLowerCase();
  const race  = document.getElementById('race-filter').value;

  const rows = allRunners.filter(r => {
    if (activeFilter !== 'all' && r.status !== activeFilter) return false;
    if (q && !r.name.toLowerCase().includes(q))              return false;
    if (race && r.race_goal !== race)                        return false;
    return true;
  });

  if (rows.length === 0) {
    document.getElementById('tbody').innerHTML =
      '<tr><td colspan="7" class="no-data">No runners match this filter</td></tr>';
    return;
  }

  const [sl, sc] = STATUS_LABELS[activeRunner?.runner_id ? 'pending' : 'pending'];

  document.getElementById('tbody').innerHTML = rows.map(r => {
    const [label, cls] = STATUS_LABELS[r.status] || ['—','s-no_plan'];
    const session = r.session ? `${r.session} · ${r.distance}km` : '—';
    const lastMsg = r.last_msg
      ? `<span style="color:${r.last_dir==='inbound'?'#333':'#00a884'}">${r.last_dir==='inbound'?'←':'→'}</span> ${r.last_msg}`
      : '<span style="color:#ccc">No messages</span>';
    const selected = activeRunner?.runner_id === r.runner_id ? 'selected' : '';
    return `<tr class="runner-row ${selected}" onclick="openPanel('${r.runner_id}')">
      <td>
        <div class="name-cell">
          <div class="avatar" style="background:${avatarColor(r.name)}">${initials(r.name)}</div>
          <div><strong>${r.name}</strong><small>${r.phone}</small></div>
        </div>
      </td>
      <td>${r.race_goal||'—'}<small>${r.weeks}</small></td>
      <td style="text-align:center">${r.weeks}</td>
      <td>${session}</td>
      <td><span class="badge ${cls}">${label}</span></td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:#555">${lastMsg}</td>
      <td>
        <button class="act-btn" title="Message" onclick="event.stopPropagation();openPanel('${r.runner_id}',true)">💬</button>
        ${r.status==='pending'?`<button class="act-btn" title="Mark complete" onclick="event.stopPropagation();markComplete('${r.runner_id}','${r.distance}')">✓</button>`:''}
      </td>
    </tr>`;
  }).join('');
}

// ── Side panel ────────────────────────────────────────────────────────────────

async function openPanel(runnerId, focusCompose = false) {
  activeRunner = { runner_id: runnerId };
  document.getElementById('panel').classList.add('open');
  renderTable(); // highlight selected row

  // Reset panel
  planChatHistory = [];
  document.getElementById('plan-chat').innerHTML = '';
  updateComposeArea('today');
  switchTab('today');
  document.getElementById('today-content').innerHTML = '<div class="loading">Loading…</div>';
  document.getElementById('conv-list').innerHTML     = '<div class="loading">Loading…</div>';
  document.getElementById('profile-content').innerHTML = '<div class="loading">Loading…</div>';
  document.getElementById('compose').value = '';

  const res  = await fetch(`/dashboard/api/runner/${runnerId}`);
  const data = await res.json();
  if (data.error) { toast(data.error, true); return; }

  const r  = data.runner;
  const p  = data.plan;
  const color = avatarColor(r.name);

  // Header
  document.getElementById('p-avatar').textContent = initials(r.name);
  document.getElementById('p-avatar').style.background = color;
  document.getElementById('p-name').textContent = r.name;
  document.getElementById('p-sub').textContent  = `${r.race_goal||'—'} · ${data.weeks} to race`;

  // Today tab
  let todayHtml = '';
  if (p) {
    todayHtml += `<div class="plan-card">
      <div class="plan-title">${p.session_type||'—'} — ${p.distance_km||0}km</div>
      <div class="plan-row">🎯 Intensity: ${p.intensity||'—'} &nbsp;·&nbsp; RPE ${p.rpe_target||'—'}</div>
      <div class="plan-notes">${p.coach_notes||'No specific notes'}</div>
    </div>`;
    if (p.runner_feedback) {
      todayHtml += `<div class="feedback-card"><strong>Runner's feedback:</strong><br>${p.runner_feedback}</div>`;
    }
    if (p.flags) {
      todayHtml += `<div class="feedback-card" style="background:#fee2e2;color:#991b1b"><strong>⚠ Flag:</strong> ${p.flags}</div>`;
    }
  } else {
    todayHtml = '<p style="color:#aaa;font-size:13px">No training plan for today.</p>';
  }
  document.getElementById('today-content').innerHTML = todayHtml;

  // History tab
  const convs = data.conversations || [];
  if (convs.length === 0) {
    document.getElementById('conv-list').innerHTML = '<p style="color:#aaa;font-size:13px">No conversation history yet.</p>';
  } else {
    document.getElementById('conv-list').innerHTML = convs.map(m => {
      const isIn = m.direction === 'inbound';
      return `<div class="bubble ${isIn?'in':'out'}">
        ${m.message}
        <div class="ts">${m.timestamp||''}</div>
      </div>`;
    }).join('');
    // scroll to bottom
    setTimeout(() => {
      const cl = document.getElementById('conv-list');
      cl.parentElement.scrollTop = cl.parentElement.scrollHeight;
    }, 50);
  }

  // Profile tab
  const inj = r.injuries && r.injuries !== 'None'
    ? `<span class="injury-tag">${r.injuries}</span>`
    : '<span style="color:#aaa">None</span>';
  document.getElementById('profile-content').innerHTML = `
    <div class="profile-row"><span class="lbl">Phone</span><span class="val">${r.phone}</span></div>
    <div class="profile-row"><span class="lbl">Fitness level</span><span class="val">${r.fitness_level||'—'}</span></div>
    <div class="profile-row"><span class="lbl">Training days/week</span><span class="val">${r.weekly_days||'—'}</span></div>
    <div class="profile-row"><span class="lbl">Race date</span><span class="val">${r.race_date||'—'}</span></div>
    <div class="profile-row"><span class="lbl">Weeks to race</span><span class="val">${data.weeks}</span></div>
    <div class="profile-row"><span class="lbl">Started</span><span class="val">${r.start_date||'—'}</span></div>
    <div class="profile-row"><span class="lbl">Payment</span><span class="val">${r.payment_status||'—'} · ₹${r.monthly_fee||'—'}/mo</span></div>
    <div class="profile-row"><span class="lbl">Injuries</span><span class="val">${inj}</span></div>
    ${r.notes ? `<div style="background:#f9f9f9;border-radius:8px;padding:10px 12px;font-size:12px;color:#555;margin-top:8px;line-height:1.5">${r.notes}</div>` : ''}
  `;

  // Coach notes
  const notes = data.coach_notes || [];
  if (notes.length > 0) {
    document.getElementById('profile-content').innerHTML +=
      `<div style="margin-top:16px"><strong style="font-size:12px;text-transform:uppercase;color:#666;letter-spacing:.05em">Coach instructions for agent</strong>` +
      notes.map(n=>`<div style="background:#f0f4ff;border-radius:6px;padding:8px 10px;margin-top:6px;font-size:12px;color:#3730a3">${n.rule_derived}</div>`).join('') + '</div>';
  }

  if (focusCompose) {
    switchTab('history');
    setTimeout(() => document.getElementById('compose').focus(), 100);
  }

  // Store coach_id for note/message actions
  document.getElementById('send-btn').dataset.runnerId = runnerId;
  document.getElementById('note-btn').dataset.coachId  = r.coach_id;
  document.getElementById('note-btn').dataset.runnerId = runnerId;
}

function closePanel() {
  const panel = document.getElementById('panel');
  panel.classList.remove('open');
  panel.style.removeProperty('width');   // clear any drag-set inline width
  activeRunner = null;
  renderTable();
}

const TAB_ORDER = ['today','history','plan','profile'];
function switchTab(name) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  const idx = TAB_ORDER.indexOf(name);
  if (idx >= 0) document.querySelectorAll('.tab')[idx].classList.add('active');
  if (name === 'plan' && activeRunner) loadPlans(activeRunner.runner_id);
  updateComposeArea(name);
}

function updateComposeArea(tabName) {
  const area = document.getElementById('compose-area');
  if (tabName === 'plan') {
    area.innerHTML = `
      <span class="compose-ai-label">✨ Plan AI — ask to create or modify this runner's plan</span>
      <textarea class="compose-plan-textarea" id="plan-ai-input"
        placeholder="e.g. Create a 6-week plan leading to the race with a taper in the last 2 weeks&#10;e.g. Add an easy 6km run next Monday&#10;e.g. What does week 3 look like?"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendPlanAI()}"></textarea>
      <div class="compose-actions" style="margin-top:8px">
        <button class="ask-ai-btn" id="ask-ai-btn" onclick="sendPlanAI()">Ask AI</button>
      </div>`;
  } else {
    area.innerHTML = `
      <label>Message runner directly (sends as coach via WhatsApp)</label>
      <textarea class="compose-textarea" id="compose" placeholder="Type a message…"></textarea>
      <div class="compose-actions">
        <button class="send-btn" id="send-btn" onclick="sendMessage()">Send WhatsApp</button>
        <button class="note-btn" id="note-btn" onclick="addNote()">Save as Instruction</button>
      </div>`;
  }
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function sendMessage() {
  const textarea = document.getElementById('compose');
  const msg = textarea?.value.trim();
  if (!msg || !activeRunner) return;
  const rid = activeRunner.runner_id;

  const btn = document.getElementById('send-btn');
  btn.disabled = true; btn.textContent = 'Sending…';
  try {
    const res  = await fetch('/dashboard/api/message', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({runner_id: rid, message: msg})
    });
    const data = await res.json();
    if (data.ok) { toast('Message sent via WhatsApp ✓'); textarea.value = ''; openPanel(rid); }
    else toast(data.error || 'Failed to send', true);
  } catch(e) { toast('Error: ' + e.message, true); }
  finally { btn.disabled = false; btn.textContent = 'Send WhatsApp'; }
}

async function addNote() {
  const textarea = document.getElementById('compose');
  const msg = textarea?.value.trim();
  if (!msg || !activeRunner) return;
  const rid = activeRunner.runner_id;
  const runner = await (await fetch(`/dashboard/api/runner/${rid}`)).json();
  const coachId = runner.runner?.coach_id;

  const btn = document.getElementById('note-btn');
  btn.disabled = true; btn.textContent = 'Saving…';
  try {
    const res  = await fetch('/dashboard/api/note', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({coach_id: coachId, runner_id: rid, note: msg})
    });
    const data = await res.json();
    if (data.ok) { toast('Instruction saved — agent will use this ✓'); textarea.value = ''; openPanel(rid); }
    else toast(data.error || 'Failed', true);
  } catch(e) { toast('Error: ' + e.message, true); }
  finally { btn.disabled = false; btn.textContent = 'Save as Instruction'; }
}

async function markComplete(runnerId, distance) {
  try {
    await fetch('/dashboard/api/complete', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({runner_id: runnerId, distance: String(distance)})
    });
    toast('Marked as completed ✓');
    await loadData();
    if (activeRunner?.runner_id === runnerId) openPanel(runnerId);
  } catch(e) { toast('Error: ' + e.message, true); }
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function toast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Manage AI ─────────────────────────────────────────────────────────────────

let maiCoachId = null;

async function openManageAI() {
  // Pick the first coach (or let user select if multiple)
  if (!coaches.length) { toast('No coaches found', true); return; }
  maiCoachId = coaches[0].id;
  document.getElementById('mai-coach-name').textContent = coaches[0].name;
  document.getElementById('mai-overlay').style.display = 'flex';
  switchMAITab('personality');
  await Promise.all([loadPrompt(), loadRules()]);
}

function closeManageAI() {
  document.getElementById('mai-overlay').style.display = 'none';
}

function switchMAITab(name) {
  document.querySelectorAll('.mai-tab').forEach((t,i) => t.classList.toggle('active', ['personality','rules'][i] === name));
  document.querySelectorAll('.mai-pane').forEach(p => p.classList.remove('active'));
  document.getElementById('mai-' + name).classList.add('active');
}

async function loadPrompt() {
  const res  = await fetch(`/dashboard/api/coach/${maiCoachId}/config`);
  const data = await res.json();
  document.getElementById('mai-prompt').value = data.active_prompt || '';
  document.getElementById('mai-active-ver').textContent = data.active_version || 'v1';

  const tbody = document.getElementById('mai-versions-tbody');
  if (!data.versions?.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:#aaa;padding:12px">No version history yet.</td></tr>';
    return;
  }
  tbody.innerHTML = data.versions.map(v => `
    <tr>
      <td><strong>${v.version}</strong></td>
      <td>${v.date || '—'}</td>
      <td>${v.active ? '<span class="ver-active">Active</span>' : '<span class="ver-old">Archived</span>'}</td>
      <td class="ver-preview">${v.preview}…</td>
      <td>${!v.active ? `<button class="act-btn" onclick="restorePrompt('${v.version}')">Restore</button>` : ''}</td>
    </tr>`).join('');
}

async function savePrompt() {
  const prompt = document.getElementById('mai-prompt').value.trim();
  if (!prompt) { toast('Prompt cannot be empty', true); return; }
  const res  = await fetch(`/dashboard/api/coach/${maiCoachId}/prompt`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({prompt})
  });
  const data = await res.json();
  if (data.ok) {
    toast(`✓ Prompt saved as ${data.version} and activated`);
    await loadPrompt();
  } else toast('Save failed', true);
}

async function restorePrompt(version) {
  if (!confirm(`Restore ${version} as the active prompt?`)) return;
  await fetch(`/dashboard/api/coach/${maiCoachId}/prompt/restore/${version}`, { method:'POST' });
  toast(`✓ Restored to ${version}`);
  await loadPrompt();
}

async function loadRules() {
  if (!maiCoachId) return;
  const showArchived = document.getElementById('show-archived')?.checked;
  const res  = await fetch(`/dashboard/api/coach/${maiCoachId}/rules`);
  const data = await res.json();
  const rules = (data.rules || []).filter(r => showArchived || r.status === 'Active');

  const SOURCE_LABELS = {
    coach_correction: ['Correction', 'src-correction'],
    coach_instruction:['Instruction','src-instruction'],
    coach_manual:     ['Manual',    'src-manual'],
    coach_dashboard:  ['Dashboard', 'src-dashboard'],
    manual:           ['Manual',    'src-manual'],
  };

  const tbody = document.getElementById('mai-rules-tbody');
  if (!rules.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:#aaa;padding:16px">No rules yet. Add one above to train the AI.</td></tr>';
    return;
  }
  tbody.innerHTML = rules.map(r => {
    const rid = r.rule_id || r._id;
    const [srcLabel, srcCls] = SOURCE_LABELS[r.source] || ['Other','src-other'];
    const isArchived = r.status === 'Archived';
    return `<tr class="${isArchived?'archived':''}">
      <td>${r.rule_derived || r.situation || '—'}</td>
      <td><span class="source-badge ${srcCls}">${srcLabel}</span></td>
      <td style="color:#aaa;font-size:12px;white-space:nowrap">${r.date_added||'—'}</td>
      <td><span class="badge ${isArchived?'s-no_plan':'s-completed'}">${r.status}</span></td>
      <td>
        <div class="rule-actions">
          ${isArchived
            ? `<button class="act-btn" onclick="ruleAction('restore','${rid}')">Restore</button>`
            : `<button class="act-btn" onclick="ruleAction('archive','${rid}')">Archive</button>`}
          <button class="act-btn del" onclick="ruleAction('delete','${rid}')">Delete</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

async function addRule() {
  const input = document.getElementById('mai-new-rule');
  const rule  = input.value.trim();
  if (!rule) return;
  await fetch(`/dashboard/api/coach/${maiCoachId}/rule`, {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({rule})
  });
  input.value = '';
  toast('Rule added — agent will use it immediately ✓');
  await loadRules();
}

async function ruleAction(action, ruleId) {
  if (action === 'delete' && !confirm('Permanently delete this rule?')) return;
  const method = action === 'delete' ? 'DELETE' : 'PUT';
  const url    = action === 'delete'
    ? `/dashboard/api/rule/${ruleId}`
    : `/dashboard/api/rule/${ruleId}/${action}`;
  await fetch(url, { method });
  toast(action === 'delete' ? 'Rule deleted' : action === 'archive' ? 'Rule archived' : 'Rule restored');
  await loadRules();
}

// ── Plan management ───────────────────────────────────────────────────────────

const SESSION_COLORS = {
  'Easy Run':'sc-easy', 'Tempo Run':'sc-tempo', 'Interval Training':'sc-interval',
  'Long Run':'sc-long',  'Recovery Run':'sc-recovery', 'Rest':'sc-rest',
  'Cross Training':'sc-cross', 'Cross-train':'sc-cross',
};

function sessionClass(type) { return SESSION_COLORS[type] || 'sc-easy'; }

async function loadPlans(runnerId) {
  document.getElementById('plan-content').innerHTML = '<div class="loading">Loading plan…</div>';
  const res  = await fetch(`/dashboard/api/runner/${runnerId}/plans?days=56`);
  const data = await res.json();
  renderPlanList(data.plans || [], runnerId);
}

function renderPlanList(plans, runnerId) {
  let html = `<div class="plan-toolbar">
    <button class="btn-generate" onclick="openGenModal()">✨ Generate Plan</button>
    <button class="btn-add" onclick="showAddForm('${runnerId}')">+ Add Session</button>
  </div>`;

  if (plans.length === 0) {
    html += '<p style="color:#aaa;font-size:13px;margin-top:12px">No upcoming sessions. Generate a plan or add individual sessions.</p>';
    document.getElementById('plan-content').innerHTML = html;
    return;
  }

  // Group by week
  const weeks = {};
  plans.forEach(p => {
    const d = new Date(p.date);
    const monday = new Date(d); monday.setDate(d.getDate() - d.getDay() + 1);
    const wk = monday.toISOString().slice(0,10);
    weeks[wk] = weeks[wk] || [];
    weeks[wk].push(p);
  });

  html += '<div class="session-list">';
  Object.keys(weeks).sort().forEach(wk => {
    const wDate = new Date(wk);
    html += `<div class="week-header">Week of ${wDate.toLocaleDateString('en-IN',{day:'numeric',month:'short'})}</div>`;
    weeks[wk].forEach(p => {
      const pid = p.plan_id || p._id;
      const d   = new Date(p.date);
      const dayStr = d.toLocaleDateString('en-IN',{weekday:'short',day:'numeric',month:'short'});
      const sc  = sessionClass(p.session_type);
      const dist = p.distance_km && p.distance_km != '0' ? `${p.distance_km}km · ` : '';
      const done = p.completed === 'TRUE' ? ' ✓' : '';
      html += `<div class="session-card ${sc}" id="sc-${pid}">
        <div class="sc-date">${dayStr}</div>
        <div class="sc-body">
          <div class="sc-title">${p.session_type||'—'}${done}</div>
          <div class="sc-meta">${dist}${p.intensity||''} · RPE ${p.rpe_target||'—'}</div>
          ${p.coach_notes ? `<div class="sc-notes">${p.coach_notes}</div>` : ''}
          <div id="ef-${pid}"></div>
        </div>
        <div class="sc-actions">
          <button class="sc-btn" onclick="showEditForm('${pid}','${runnerId}')">Edit</button>
          <button class="sc-btn del" onclick="deletePlan('${pid}','${runnerId}')">✕</button>
        </div>
      </div>`;
    });
  });
  html += '</div>';
  document.getElementById('plan-content').innerHTML = html;
}

function showAddForm(runnerId) {
  const tomorrow = new Date(); tomorrow.setDate(tomorrow.getDate()+1);
  const dateStr  = tomorrow.toISOString().slice(0,10);
  const formHtml = `<div class="edit-form" id="add-form" style="margin-bottom:12px">
    <strong style="font-size:12px">Add Session</strong>
    <div class="ef-row" style="margin-top:8px">
      <div><label>Date</label><input type="date" id="ef-date" value="${dateStr}"></div>
      <div><label>Session type</label><select id="ef-type">
        <option>Easy Run</option><option>Tempo Run</option><option>Interval Training</option>
        <option>Long Run</option><option>Recovery Run</option><option>Cross Training</option><option>Rest</option>
      </select></div>
    </div>
    <div class="ef-row">
      <div><label>Distance (km)</label><input type="number" id="ef-dist" placeholder="0" step="0.5"></div>
      <div><label>Intensity</label><select id="ef-intensity">
        <option>Zone 2</option><option>Threshold</option><option>VO2 Max</option><option>Easy</option><option>Rest</option>
      </select></div>
    </div>
    <div class="ef-row">
      <div><label>RPE target</label><input id="ef-rpe" placeholder="4-5"></div>
      <div></div>
    </div>
    <label>Coach notes</label>
    <textarea id="ef-notes" rows="2" placeholder="Specific instructions for this session…" style="margin-bottom:6px"></textarea>
    <div class="edit-form-actions">
      <button class="ef-save" onclick="saveNewPlan('${runnerId}')">Save</button>
      <button class="ef-cancel" onclick="document.getElementById('add-form').remove()">Cancel</button>
    </div>
  </div>`;
  document.getElementById('plan-content').insertAdjacentHTML('afterbegin', formHtml);
}

async function saveNewPlan(runnerId) {
  const payload = {
    runner_id:    runnerId,
    date:         document.getElementById('ef-date').value,
    session_type: document.getElementById('ef-type').value,
    day_type:     document.getElementById('ef-type').value === 'Rest' ? 'Rest' : 'Run',
    distance_km:  document.getElementById('ef-dist').value || '0',
    intensity:    document.getElementById('ef-intensity').value,
    rpe_target:   document.getElementById('ef-rpe').value || '4-5',
    coach_notes:  document.getElementById('ef-notes').value,
  };
  const res = await fetch('/dashboard/api/plan', {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
  });
  if ((await res.json()).ok) { toast('Session added ✓'); loadPlans(runnerId); }
}

function showEditForm(planId, runnerId) {
  // Find existing data from DOM
  const card = document.getElementById(`sc-${planId}`);
  const existing = document.getElementById(`ef-${planId}`);
  if (existing.innerHTML) { existing.innerHTML = ''; return; }

  existing.innerHTML = `<div class="edit-form" style="margin-top:8px">
    <div class="ef-row">
      <div><label>Session type</label><select id="eft-type-${planId}">
        <option>Easy Run</option><option>Tempo Run</option><option>Interval Training</option>
        <option>Long Run</option><option>Recovery Run</option><option>Cross Training</option><option>Rest</option>
      </select></div>
      <div><label>Distance (km)</label><input id="eft-dist-${planId}" type="number" step="0.5" placeholder="0"></div>
    </div>
    <div class="ef-row">
      <div><label>Intensity</label><select id="eft-int-${planId}">
        <option>Zone 2</option><option>Threshold</option><option>VO2 Max</option><option>Easy</option><option>Rest</option>
      </select></div>
      <div><label>RPE target</label><input id="eft-rpe-${planId}" placeholder="4-5"></div>
    </div>
    <label>Coach notes</label>
    <textarea id="eft-notes-${planId}" rows="2" style="margin-bottom:6px" placeholder="Updated instructions…"></textarea>
    <div class="edit-form-actions">
      <button class="ef-save" onclick="savePlanEdit('${planId}','${runnerId}')">Save</button>
      <button class="ef-cancel" onclick="document.getElementById('ef-${planId}').innerHTML=''">Cancel</button>
    </div>
  </div>`;
}

async function savePlanEdit(planId, runnerId) {
  const fields = {};
  const t = document.getElementById(`eft-type-${planId}`)?.value;
  const d = document.getElementById(`eft-dist-${planId}`)?.value;
  const i = document.getElementById(`eft-int-${planId}`)?.value;
  const r = document.getElementById(`eft-rpe-${planId}`)?.value;
  const n = document.getElementById(`eft-notes-${planId}`)?.value;
  if (t) { fields.session_type = t; fields.day_type = t === 'Rest' ? 'Rest' : 'Run'; }
  if (d) fields.distance_km = d;
  if (i) fields.intensity    = i;
  if (r) fields.rpe_target   = r;
  if (n !== undefined) fields.coach_notes = n;

  const res = await fetch(`/dashboard/api/plan/${planId}`, {
    method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(fields)
  });
  if ((await res.json()).ok) { toast('Session updated ✓'); loadPlans(runnerId); }
}

async function deletePlan(planId, runnerId) {
  if (!confirm('Delete this session?')) return;
  await fetch(`/dashboard/api/plan/${planId}`, { method:'DELETE' });
  toast('Session deleted'); loadPlans(runnerId);
}

// ── Plan AI chat ──────────────────────────────────────────────────────────────

let planChatHistory   = [];
let pendingAISessions = [];
let pendingDeleteFirst = false;

async function sendPlanAI() {
  const input = document.getElementById('plan-ai-input');
  const msg   = input?.value.trim();
  if (!msg || !activeRunner) return;

  const btn = document.getElementById('ask-ai-btn');
  btn.disabled = true; btn.textContent = '⏳ Thinking…';
  input.value = '';

  addPlanChatBubble(msg, 'coach');
  planChatHistory.push({role: 'user', content: msg});

  // Typing indicator
  const typingId = 'typing-' + Date.now();
  document.getElementById('plan-chat').insertAdjacentHTML('beforeend',
    `<div class="pchat-msg ai" id="${typingId}" style="opacity:.6">Analysing runner profile and plan…</div>`);
  document.getElementById('tab-plan').scrollTop = 9999;

  try {
    const res  = await fetch(`/dashboard/api/runner/${activeRunner.runner_id}/plan/chat`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({message: msg, history: planChatHistory.slice(-6)})
    });
    const data = await res.json();
    document.getElementById(typingId)?.remove();

    if (data.error) { toast(data.error, true); return; }

    planChatHistory.push({role: 'assistant', content: data.message});

    const isReplace = data.action === 'replace_sessions';
    if ((data.action === 'create_sessions' || isReplace) && data.sessions?.length > 0) {
      pendingAISessions  = data.sessions;
      pendingDeleteFirst = isReplace;
      addPlanChatBubble(data.message, 'ai', data.sessions, isReplace);
    } else {
      addPlanChatBubble(data.message, 'ai');
    }
  } catch(e) {
    document.getElementById(typingId)?.remove();
    toast('Error: ' + e.message, true);
  } finally {
    btn.disabled = false; btn.textContent = 'Ask AI';
    input?.focus();
  }
}

function addPlanChatBubble(text, role, sessions = null, deleteFirst = false) {
  const chat = document.getElementById('plan-chat');
  const time = new Date().toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit'});

  let sessionHtml = '';
  if (sessions && sessions.length > 0) {
    const rows = sessions.slice(0,8).map(s =>
      `<tr><td>${s.date}</td><td>${s.session_type}</td><td>${s.distance_km||0}km</td><td>${s.intensity}</td></tr>`
    ).join('');
    const more = sessions.length > 8 ? `<tr><td colspan="4" style="color:#aaa;text-align:center">+${sessions.length-8} more sessions</td></tr>` : '';
    sessionHtml = `<div class="plan-preview-box" style="margin-top:8px">
      <table>
        <thead><tr><th>Date</th><th>Type</th><th>Dist</th><th>Intensity</th></tr></thead>
        <tbody>${rows}${more}</tbody>
      </table>
      <div class="plan-preview-actions">
        ${deleteFirst ? `<div style="font-size:11px;color:#c62828;margin-bottom:6px;width:100%">⚠ This will delete all existing future sessions before saving.</div>` : ''}
        <button class="ef-save plan-save-btn" onclick="saveAISessions(this)" style="${deleteFirst?'background:#e53935':''}">${deleteFirst ? `Delete existing & save ${sessions.length} sessions` : `Save ${sessions.length} sessions to plan`}</button>
        <button class="ef-cancel plan-discard-btn" onclick="discardAISessions()">Discard</button>
      </div>
    </div>`;
  }

  chat.insertAdjacentHTML('beforeend', `
    <div class="pchat-msg ${role}">
      ${text.replace(/\n/g,'<br>')}
      ${sessionHtml}
      <div class="pchat-meta">${time}</div>
    </div>`);

  document.getElementById('tab-plan').scrollTop = 9999;
}

async function saveAISessions(btn) {
  if (!pendingAISessions.length || !activeRunner) return;

  // Immediately disable all save buttons to prevent double-click
  document.querySelectorAll('.plan-save-btn').forEach(b => {
    b.disabled = true;
    b.textContent = 'Saving…';
  });
  document.querySelectorAll('.plan-discard-btn').forEach(b => { b.disabled = true; });

  try {
    const res  = await fetch('/dashboard/api/plans/bulk', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        runner_id:    activeRunner.runner_id,
        sessions:     pendingAISessions,
        delete_first: pendingDeleteFirst,
      })
    });
    const data = await res.json();
    if (data.ok) {
      const msg = pendingDeleteFirst
        ? `✓ Deleted ${data.deleted} old sessions, saved ${data.saved} new ones`
        : `✓ ${data.saved} sessions saved`;
      toast(msg);
      pendingAISessions  = [];
      pendingDeleteFirst = false;
      // Mark buttons as done (don't re-enable — plan is saved)
      document.querySelectorAll('.plan-save-btn').forEach(b => { b.textContent = 'Saved ✓'; });
      document.querySelectorAll('.plan-discard-btn').forEach(b => { b.style.display = 'none'; });
      loadPlans(activeRunner.runner_id);
    } else {
      toast('Save failed — try again', true);
      // Re-enable on error so coach can retry
      document.querySelectorAll('.plan-save-btn').forEach(b => {
        b.disabled = false;
        b.textContent = `Save ${pendingAISessions.length} sessions to plan`;
      });
      document.querySelectorAll('.plan-discard-btn').forEach(b => { b.disabled = false; });
    }
  } catch(e) {
    toast('Error: ' + e.message, true);
    document.querySelectorAll('.plan-save-btn').forEach(b => {
      b.disabled = false;
      b.textContent = `Save ${pendingAISessions.length} sessions to plan`;
    });
    document.querySelectorAll('.plan-discard-btn').forEach(b => { b.disabled = false; });
  }
}

function discardAISessions() {
  pendingAISessions  = [];
  pendingDeleteFirst = false;
  document.querySelectorAll('.plan-save-btn').forEach(b => { b.disabled = true; b.style.display='none'; });
  document.querySelectorAll('.plan-discard-btn').forEach(b => { b.disabled = true; });
  addPlanChatBubble('Sessions discarded. Ask me again if you want a different plan.', 'ai');
}

// ── Generate plan modal ───────────────────────────────────────────────────────

let genPreviewSessions = [];
let genTargetRunner    = null;

function openGenModal() {
  if (!activeRunner) return;
  genTargetRunner = activeRunner.runner_id;
  // Reset
  document.getElementById('gen-form').style.display = 'block';
  document.getElementById('gen-preview').style.display = 'none';
  document.getElementById('gen-modal-ftr').innerHTML =
    '<button class="btn-secondary" onclick="closeGenModal()">Cancel</button>' +
    '<button class="btn-purple" id="gen-btn" onclick="generatePlan()">✨ Generate with AI</button>';
  document.getElementById('gen-start').value = new Date(Date.now()+86400000).toISOString().slice(0,10);
  document.getElementById('gen-notes').value = '';
  document.getElementById('gen-overlay').style.display = 'flex';
}

function closeGenModal() { document.getElementById('gen-overlay').style.display = 'none'; }

async function generatePlan() {
  const btn = document.getElementById('gen-btn');
  btn.disabled = true; btn.textContent = '⏳ Generating…';

  const payload = {
    weeks:      parseInt(document.getElementById('gen-weeks').value),
    start_date: document.getElementById('gen-start').value,
    notes:      document.getElementById('gen-notes').value,
  };

  try {
    const res  = await fetch(`/dashboard/api/runner/${genTargetRunner}/plans/generate`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.error) { toast(data.error, true); return; }

    genPreviewSessions = data.sessions;
    renderPreview(genPreviewSessions);
    document.getElementById('gen-form').style.display = 'none';
    document.getElementById('gen-preview').style.display = 'block';
    document.getElementById('gen-modal-ftr').innerHTML =
      `<button class="btn-secondary" onclick="closeGenModal()">Discard</button>` +
      `<button class="btn-secondary" onclick="backToGenForm()">← Regenerate</button>` +
      `<button class="btn-primary" onclick="savePlanPreview()">Save ${genPreviewSessions.length} sessions</button>`;
  } catch(e) { toast('Error: ' + e.message, true); }
  finally { btn.disabled = false; btn.textContent = '✨ Generate with AI'; }
}

function backToGenForm() {
  document.getElementById('gen-form').style.display = 'block';
  document.getElementById('gen-preview').style.display = 'none';
  document.getElementById('gen-modal-ftr').innerHTML =
    '<button class="btn-secondary" onclick="closeGenModal()">Cancel</button>' +
    '<button class="btn-purple" id="gen-btn" onclick="generatePlan()">✨ Generate with AI</button>';
}

function renderPreview(sessions) {
  document.getElementById('preview-count').textContent =
    `${sessions.length} sessions generated — click any cell to edit before saving.`;
  const tbody = document.getElementById('preview-tbody');
  tbody.innerHTML = sessions.map((s, i) => {
    const d = new Date(s.date);
    const dateStr = d.toLocaleDateString('en-IN',{day:'numeric',month:'short'});
    const dayStr  = d.toLocaleDateString('en-IN',{weekday:'short'});
    const isRest  = (s.session_type||'').toLowerCase().includes('rest');
    const rowStyle = isRest ? 'style="color:#aaa"' : '';
    return `<tr ${rowStyle}>
      <td><strong>${dateStr}</strong></td>
      <td>${dayStr}</td>
      <td><input value="${s.session_type||''}" onchange="genPreviewSessions[${i}].session_type=this.value" style="min-width:120px"></td>
      <td><input value="${s.distance_km||0}" type="number" step="0.5" onchange="genPreviewSessions[${i}].distance_km=this.value" style="width:55px"></td>
      <td><input value="${s.intensity||''}" onchange="genPreviewSessions[${i}].intensity=this.value" style="min-width:90px"></td>
      <td><input value="${s.rpe_target||''}" onchange="genPreviewSessions[${i}].rpe_target=this.value" style="width:55px"></td>
      <td><input class="wide" value="${(s.coach_notes||'').replace(/"/g,'&quot;')}" onchange="genPreviewSessions[${i}].coach_notes=this.value"></td>
      <td><button class="sc-btn del" title="Remove" onclick="genPreviewSessions.splice(${i},1);renderPreview(genPreviewSessions)">✕</button></td>
    </tr>`;
  }).join('');
}

async function savePlanPreview() {
  const res = await fetch('/dashboard/api/plans/bulk', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ runner_id: genTargetRunner, sessions: genPreviewSessions })
  });
  const data = await res.json();
  if (data.ok) {
    toast(`✓ ${data.saved} sessions saved to training plan`);
    closeGenModal();
    loadPlans(genTargetRunner);
    switchTab('plan');
  } else { toast('Save failed', true); }
}

// ── Panel drag resize ─────────────────────────────────────────────────────────

(function() {
  const handle = document.getElementById('drag-handle');
  const panel  = document.getElementById('panel');
  let dragging = false, startX = 0, startW = 0;

  handle.addEventListener('mousedown', e => {
    dragging = true;
    startX   = e.clientX;
    startW   = panel.offsetWidth;
    handle.classList.add('dragging');
    document.body.style.cursor     = 'col-resize';
    document.body.style.userSelect = 'none';
    // Disable pointer events on panel content during drag so nothing inside intercepts
    panel.querySelector('.panel-inner').style.pointerEvents = 'none';
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const diff = startX - e.clientX;
    const newW = Math.min(Math.max(startW + diff, 320), window.innerWidth * 0.75);
    panel.style.width = newW + 'px';
  });

  // Catch mouseup anywhere — including outside the window on mouseout
  ['mouseup', 'mouseleave'].forEach(evt => {
    document.addEventListener(evt, (e) => {
      if (!dragging) return;
      if (evt === 'mouseleave' && e.target !== document.documentElement) return;
      dragging = false;
      handle.classList.remove('dragging');
      document.body.style.cursor     = '';
      document.body.style.userSelect = '';
      panel.querySelector('.panel-inner').style.pointerEvents = '';
    });
  });
})();


// ── Init ──────────────────────────────────────────────────────────────────────
loadData();
</script>
</body>
</html>"""
