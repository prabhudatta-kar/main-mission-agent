"""
Session-based auth for coach and admin dashboard routes.

Cookie:   mm_session — HMAC-SHA256 signed, base64url encoded, 7-day expiry.
Roles:    admin | coach

Env vars:
  SESSION_SECRET      — random 32+ char string (keep secret)
  ADMIN_EMAIL         — admin login email
  ADMIN_PASSWORD      — admin login password
  COACH_ACCESS_CODE   — shared passcode for all coaches
"""
import base64
import hashlib
import hmac
import time
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse as StarletteRedirect

from config.settings import (
    ADMIN_EMAIL, ADMIN_PASSWORD, COACH_ACCESS_CODE, SESSION_SECRET,
)
from integrations.firebase_db import sheets

router = APIRouter()

_COOKIE      = "mm_session"
_EXPIRY_SECS = 7 * 24 * 3600

# Paths that require a valid session
_PROTECTED = ("/dashboard", "/sysobservations", "/test")


# ── Middleware — protects all _PROTECTED paths ────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _PROTECTED):
            if not get_session(request):
                return StarletteRedirect(f"/login?next={path}", status_code=302)
        return await call_next(request)


# ── Token helpers ─────────────────────────────────────────────────────────────

def _sign(payload: str) -> str:
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode()


def _make_token(email: str, role: str) -> str:
    payload = f"{email}|{role}|{int(time.time())}"
    return base64.urlsafe_b64encode(f"{payload}.{_sign(payload)}".encode()).decode()


def get_session(request: Request) -> Optional[dict]:
    """Returns {email, role} if the session cookie is valid, else None."""
    token = request.cookies.get(_COOKIE)
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = decoded.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        email, role, issued_at = payload.split("|")
        if time.time() - int(issued_at) > _EXPIRY_SECS:
            return None
        return {"email": email, "role": role}
    except Exception:
        return None


# ── Credential verification ───────────────────────────────────────────────────

def _verify(email: str, password: str) -> Optional[str]:
    """Returns role if credentials are valid, else None."""
    email = email.strip().lower()

    if ADMIN_EMAIL and ADMIN_PASSWORD:
        if email == ADMIN_EMAIL.strip().lower() and password == ADMIN_PASSWORD:
            return "admin"

    if COACH_ACCESS_CODE and password == COACH_ACCESS_CODE:
        for c in sheets.get_all_active_coaches():
            coach_email = (c.get("operatorEmail") or c.get("email") or "").lower()
            if coach_email == email:
                return "coach"

    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/dashboard", error: str = ""):
    if get_session(request):
        return RedirectResponse(next, status_code=302)
    return HTMLResponse(_login_html(next=next, error=error))


@router.post("/login")
async def login_submit(
    request: Request,
    email:    str = Form(...),
    password: str = Form(...),
    next:     str = Form(default="/dashboard"),
):
    role = _verify(email, password)
    if not role:
        return HTMLResponse(_login_html(next=next, error="Invalid email or password"), status_code=401)

    token = _make_token(email.strip().lower(), role)
    response = RedirectResponse(next, status_code=302)
    response.set_cookie(
        _COOKIE, token,
        max_age=_EXPIRY_SECS,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(_COOKIE)
    return response


# ── Login page ────────────────────────────────────────────────────────────────

def _login_html(next: str = "/dashboard", error: str = "") -> str:
    err = f'<div class="error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in — Main Mission</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;display:flex;align-items:center;justify-content:center;min-height:100vh;color:#e0e0e0}}
.card{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:16px;padding:40px 36px;width:100%;max-width:400px}}
.logo{{text-align:center;margin-bottom:28px}}
.logo h1{{font-size:22px;font-weight:800;color:#fff;letter-spacing:-.5px}}
.logo p{{font-size:13px;color:#666;margin-top:4px}}
label{{display:block;font-size:12px;font-weight:600;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}}
input{{width:100%;background:#12151f;border:1px solid #2a2d3a;border-radius:8px;padding:11px 14px;color:#fff;font-size:14px;outline:none;transition:border .15s}}
input:focus{{border-color:#5c6bc0}}
.field{{margin-bottom:18px}}
.btn{{width:100%;background:#5c6bc0;color:#fff;border:none;border-radius:8px;padding:12px;font-size:14px;font-weight:700;cursor:pointer;margin-top:4px}}
.btn:hover{{background:#4a57a8}}
.error{{background:#2d1515;border:1px solid #5c2020;color:#ff8a80;border-radius:8px;padding:10px 14px;font-size:13px;margin-bottom:18px}}
.hint{{font-size:12px;color:#555;text-align:center;margin-top:20px}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <h1>Main Mission</h1>
    <p>Coach &amp; Admin Portal</p>
  </div>
  {err}
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{next}">
    <div class="field">
      <label>Email</label>
      <input type="email" name="email" placeholder="you@example.com" required autofocus>
    </div>
    <div class="field">
      <label>Password</label>
      <input type="password" name="password" placeholder="••••••••" required>
    </div>
    <button class="btn" type="submit">Sign in</button>
  </form>
  <p class="hint">Coaches: use your email + the team access code</p>
</div>
</body>
</html>"""
