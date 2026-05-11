"""
Simple entry-code auth for all dashboard routes.
Set DASHBOARD_CODE in Railway env vars. Leave empty to disable protection.

Cookie: mm_auth — HMAC-signed, 30-day expiry.
"""
import hashlib
import hmac
import time
import base64

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse as StarletteRedirect

from config.settings import DASHBOARD_CODE, SESSION_SECRET

router   = APIRouter()
_COOKIE  = "mm_auth"
_EXPIRY  = 30 * 24 * 3600   # 30 days

_PROTECTED = ("/dashboard", "/sysobservations", "/coachobservations", "/test")


# ── Middleware ────────────────────────────────────────────────────────────────

class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not DASHBOARD_CODE:
            return await call_next(request)   # protection disabled
        path = request.url.path
        if any(path.startswith(p) for p in _PROTECTED):
            if not _valid_cookie(request):
                return StarletteRedirect(f"/login?next={path}", status_code=302)
        return await call_next(request)


# ── Token helpers ─────────────────────────────────────────────────────────────

def _sign(payload: str) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
    ).decode()


def _make_cookie() -> str:
    payload = str(int(time.time()))
    return base64.urlsafe_b64encode(f"{payload}.{_sign(payload)}".encode()).decode()


def _valid_cookie(request: Request) -> bool:
    token = request.cookies.get(_COOKIE, "")
    if not token:
        return False
    try:
        decoded  = base64.urlsafe_b64decode(token.encode()).decode()
        payload, sig = decoded.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return False
        return time.time() - int(payload) < _EXPIRY
    except Exception:
        return False


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/dashboard", error: str = ""):
    if not DASHBOARD_CODE or _valid_cookie(request):
        return RedirectResponse(next, status_code=302)
    err = f'<p style="color:#ef4444;font-size:13px;margin-bottom:12px">{error}</p>' if error else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Main Mission — Enter Code</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;
  display:flex;align-items:center;justify-content:center;min-height:100vh}}
.card{{background:#1a1d27;border:1px solid #2a2d3a;border-radius:16px;padding:40px 36px;
  width:100%;max-width:360px;text-align:center}}
h1{{font-size:20px;font-weight:800;color:#fff;margin-bottom:6px}}
p{{font-size:13px;color:#666;margin-bottom:24px}}
input{{width:100%;background:#12151f;border:1px solid #2a2d3a;border-radius:8px;
  padding:12px 14px;color:#fff;font-size:18px;letter-spacing:4px;text-align:center;
  outline:none;margin-bottom:14px}}
input:focus{{border-color:#5c6bc0}}
button{{width:100%;background:#5c6bc0;color:#fff;border:none;border-radius:8px;
  padding:12px;font-size:14px;font-weight:700;cursor:pointer}}
button:hover{{background:#4a57a8}}
</style>
</head>
<body>
<div class="card">
  <h1>Main Mission</h1>
  <p>Enter your access code to continue</p>
  {err}
  <form method="post" action="/login">
    <input type="hidden" name="next" value="{next}">
    <input type="password" name="code" placeholder="••••••" autofocus autocomplete="off">
    <button type="submit">Enter</button>
  </form>
</div>
</body>
</html>""")


@router.post("/login")
async def login_submit(
    request: Request,
    code: str = Form(...),
    next: str = Form(default="/dashboard"),
):
    if not DASHBOARD_CODE or code.strip() == DASHBOARD_CODE:
        response = RedirectResponse(next, status_code=302)
        response.set_cookie(_COOKIE, _make_cookie(),
                            max_age=_EXPIRY, httponly=True, samesite="lax")
        return response
    page = await login_page(request, next=next, error="Wrong code — try again")
    page.status_code = 401
    return page


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(_COOKIE)
    return response
