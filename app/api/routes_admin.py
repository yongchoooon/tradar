"""Lightweight admin routes (single password login)."""

from __future__ import annotations

import hmac
import hashlib
import os
import time

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

_COOKIE_NAME = "admin_session"


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _cookie_secret() -> str:
    secret = _env("ADMIN_COOKIE_SECRET")
    if secret:
        return secret
    password = _env("ADMIN_PASSWORD")
    return f"{password}-admin-cookie"


def _sign_ts(ts: str) -> str:
    secret = _cookie_secret().encode("utf-8")
    return hmac.new(secret, ts.encode("utf-8"), hashlib.sha256).hexdigest()


def _build_cookie() -> str:
    ts = str(int(time.time()))
    return f"{ts}.{_sign_ts(ts)}"


def _is_cookie_valid(cookie: str | None) -> bool:
    if not cookie or "." not in cookie:
        return False
    ts, sig = cookie.split(".", 1)
    if not ts.isdigit():
        return False
    ttl = int(_env("ADMIN_SESSION_TTL_SECONDS", "86400"))
    if int(time.time()) - int(ts) > ttl:
        return False
    expected = _sign_ts(ts)
    return hmac.compare_digest(sig, expected)


def _require_admin(request: Request) -> bool:
    return _is_cookie_valid(request.cookies.get(_COOKIE_NAME))


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request) -> str:
    error = request.query_params.get("error")
    error_html = (
        '<p style="color:#b91c1c;margin-top:0.5rem;">Invalid password.</p>'
        if error
        else ""
    )
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>T-RADAR Admin Login</title>
    <style>
      body {{ font-family: system-ui, sans-serif; background:#f6f8fc; margin:0; padding:2rem; }}
      .card {{ max-width:420px; margin:8vh auto; background:#fff; padding:2rem; border-radius:16px;
        box-shadow:0 10px 30px rgba(15,23,42,0.08); }}
      h1 {{ margin:0 0 0.5rem 0; font-size:1.4rem; }}
      label {{ display:block; margin:1rem 0 0.25rem; font-weight:600; }}
      input {{ width:100%; padding:0.6rem 0.8rem; border:1px solid #e2e8f0; border-radius:10px; }}
      button {{ margin-top:1rem; width:100%; padding:0.7rem; border:none; border-radius:10px;
        background:#1d4ed8; color:#fff; font-weight:700; cursor:pointer; }}
      .hint {{ color:#64748b; font-size:0.85rem; }}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Admin Login</h1>
      <p class="hint">Enter the admin password to continue.</p>
      <form method="post" action="/admin/login">
        <label>Password</label>
        <input type="password" name="password" required/>
        <button type="submit">Sign in</button>
      </form>
      {error_html}
    </div>
  </body>
</html>
"""


@router.post("/admin/login")
def admin_login(password: str = Form(...)) -> Response:
    admin_password = _env("ADMIN_PASSWORD")
    if not admin_password:
        return HTMLResponse("ADMIN_PASSWORD is not set.", status_code=500)
    if password != admin_password:
        return RedirectResponse(url="/admin/login?error=1", status_code=303)
    response = RedirectResponse(url="/admin", status_code=303)
    cookie = _build_cookie()
    secure = _env("APP_ENV", "dev").lower() == "prod"
    response.set_cookie(
        _COOKIE_NAME,
        cookie,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=int(_env("ADMIN_SESSION_TTL_SECONDS", "86400")),
        path="/",
    )
    return response


@router.get("/admin/logout")
def admin_logout() -> Response:
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(_COOKIE_NAME, path="/")
    return response


@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request) -> Response:
    if not _require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>T-RADAR Admin</title>
    <style>
      body { font-family: system-ui, sans-serif; background:#f6f8fc; margin:0; padding:2rem; }
      header { display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; }
      .card { background:#fff; padding:1.5rem; border-radius:16px; box-shadow:0 8px 24px rgba(15,23,42,0.08); }
      .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(240px,1fr)); gap:1rem; }
      .muted { color:#64748b; font-size:0.9rem; }
      a.button { text-decoration:none; padding:0.5rem 0.8rem; border-radius:10px; background:#e2e8f0; color:#0f172a; }
    </style>
  </head>
  <body>
    <header>
      <h1>T-RADAR Admin</h1>
      <a class="button" href="/admin/logout">Logout</a>
    </header>
    <div class="grid">
      <div class="card">
        <h3>Usage logs</h3>
        <p class="muted">S3 log tables will appear here.</p>
      </div>
      <div class="card">
        <h3>Summary</h3>
        <p class="muted">Totals and charts will be added next.</p>
      </div>
      <div class="card">
        <h3>Filters</h3>
        <p class="muted">Date/model filters will be added next.</p>
      </div>
    </div>
  </body>
</html>
"""
    )
