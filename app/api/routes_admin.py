"""Lightweight admin routes (single password login)."""

from __future__ import annotations

import hmac
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services import log_storage

router = APIRouter()

_COOKIE_NAME = "admin_session"
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


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


def _render_template(name: str, **replacements: str) -> str:
    path = _TEMPLATES_DIR / name
    html = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        html = html.replace(f"{{{{{key}}}}}", value)
    return html


_LOG_TYPES = {
    "ai_agent": "openai_ai_agent_usage/",
    "search": "search_usage/",
    "variants": "variants_openai_usage/",
    "debug": "simulation_debug/",
}


def _ensure_s3_available() -> Tuple[str, Any]:
    if not log_storage.s3_logs_enabled():
        raise HTTPException(status_code=503, detail="S3 logging is disabled.")
    bucket = log_storage._bucket_name()
    if not bucket:
        raise HTTPException(status_code=503, detail="S3 bucket is not configured.")
    try:
        client = log_storage._s3_client()
    except Exception as exc:  # pragma: no cover - runtime guard
        raise HTTPException(status_code=503, detail=f"S3 client unavailable: {exc}") from exc
    return bucket, client


def _list_objects(prefix: str) -> List[Dict[str, Any]]:
    bucket, client = _ensure_s3_available()
    objects: List[Dict[str, Any]] = []
    token: str | None = None
    while True:
        params = {"Bucket": bucket, "Prefix": f"logs/{prefix}"}
        if token:
            params["ContinuationToken"] = token
        response = client.list_objects_v2(**params)
        for item in response.get("Contents", []) or []:
            key = item.get("Key")
            if not key:
                continue
            objects.append(
                {
                    "key": key,
                    "last_modified": item.get("LastModified"),
                    "size": item.get("Size", 0),
                }
            )
        if not response.get("IsTruncated"):
            break
        token = response.get("NextContinuationToken")
        if not token:
            break
    objects.sort(
        key=lambda item: item.get("last_modified") or datetime.min, reverse=True
    )
    return objects


def _get_object_text(key: str) -> Tuple[str, str]:
    bucket, client = _ensure_s3_available()
    response = client.get_object(Bucket=bucket, Key=key)
    body = response.get("Body")
    raw = body.read() if body else b""
    content_type = response.get("ContentType") or "text/plain"
    text = raw.decode("utf-8", errors="replace")
    return text, content_type


def _parse_ai_agent_log(payload: Dict[str, Any]) -> Dict[str, Any]:
    events = payload.get("events") or []
    total_cost = payload.get("total_cost_usd")
    if total_cost is None and events:
        last = events[-1]
        total_cost = last.get("total_cost_usd")
    if total_cost is None and events:
        total_cost = sum(float(ev.get("call_cost_usd") or 0) for ev in events)
    return {
        "run_id": payload.get("simulation_run_id") or "",
        "query_title": payload.get("query_title") or "",
        "total_calls": payload.get("total_calls") or len(events),
        "total_cost_usd": float(total_cost or 0),
        "client_ip": payload.get("client_ip") or "",
        "user_agent": payload.get("user_agent") or "",
    }


def _parse_variants_log(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": payload.get("timestamp") or "",
        "query_text": payload.get("query_text") or "",
        "model": payload.get("model") or "",
        "total_tokens": payload.get("total_tokens") or 0,
        "total_cost_usd": float(payload.get("total_cost_usd") or 0),
        "client_ip": payload.get("client_ip") or "",
        "language_mode": payload.get("language_mode") or "",
        "variants_count": payload.get("variants_count") or 0,
    }


def _parse_search_log(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = payload.get("query") or {}
    result_counts = payload.get("result_counts") or {}
    total_results = (
        (result_counts.get("image_top") or 0)
        + (result_counts.get("image_misc") or 0)
        + (result_counts.get("text_top") or 0)
        + (result_counts.get("text_misc") or 0)
    )
    return {
        "timestamp": payload.get("timestamp") or "",
        "search_id": payload.get("search_id") or "",
        "query_text": query.get("text") or "",
        "goods_classes": ", ".join(query.get("goods_classes") or []),
        "group_codes": ", ".join(query.get("group_codes") or []),
        "total_results": total_results,
        "client_ip": payload.get("client_ip") or "",
        "user_agent": payload.get("user_agent") or "",
    }


def _parse_debug_key(key: str) -> Dict[str, Any]:
    filename = key.split("/")[-1]
    run_tag = ""
    app_no = ""
    file_type = ""
    match = re.match(r"(.+?)_(\d+)_([a-z]+)\.(json|txt)$", filename)
    if match:
        run_tag, app_no, file_type = match.group(1), match.group(2), match.group(3)
    else:
        overall_match = re.match(r"(.+?)_overall_([a-z]+)\.(json|txt)$", filename)
        if overall_match:
            run_tag, file_type = overall_match.group(1), overall_match.group(2)
            app_no = "overall"
    return {
        "run_tag": run_tag,
        "app_no": app_no,
        "file_type": file_type,
    }


def _extract_titles_from_context(context: str) -> Tuple[str, str]:
    if not context:
        return "", ""
    user_title = ""
    candidate_title = ""
    user_match = re.search(r"-\s*명칭:\s*(.+)", context)
    if user_match:
        user_title = user_match.group(1).strip()
    candidate_match = re.search(r"-\s*제목:\s*(.+)", context)
    if candidate_match:
        candidate_title = candidate_match.group(1).strip()
        if " (출원번호" in candidate_title:
            candidate_title = candidate_title.split(" (출원번호", 1)[0].strip()
    return user_title, candidate_title


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request) -> str:
    error = request.query_params.get("error")
    error_html = (
        '<p class="error">Invalid password.</p>'
        if error
        else ""
    )
    return _render_template("admin_login.html", ERROR_HTML=error_html)


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
    return HTMLResponse(_render_template("admin_home.html"))


@router.get("/admin/api/logs")
def admin_logs(request: Request, type: str, limit: int | None = None) -> JSONResponse:
    if not _require_admin(request):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if type not in _LOG_TYPES:
        raise HTTPException(status_code=400, detail="Invalid log type")

    prefix = _LOG_TYPES[type]
    objects = _list_objects(prefix)
    max_scan = int(_env("ADMIN_LOG_MAX_SCAN", "2000"))
    truncated = len(objects) > max_scan
    scan_objects = objects[:max_scan]

    items: List[Dict[str, Any]] = []
    total_cost = 0.0

    if type == "debug":
        for obj in scan_objects:
            parsed = _parse_debug_key(obj["key"])
            items.append(
                {
                    "key": obj["key"],
                    "last_modified": obj["last_modified"].isoformat()
                    if obj.get("last_modified")
                    else "",
                    "size": obj.get("size", 0),
                    "run_tag": parsed.get("run_tag"),
                    "app_no": parsed.get("app_no"),
                    "file_type": parsed.get("file_type"),
                }
            )
        if limit:
            items = items[:limit]
        return JSONResponse({"items": items})

    for obj in scan_objects:
        try:
            text, _ = _get_object_text(obj["key"])
            payload = json.loads(text)
        except Exception:
            continue
        if type == "ai_agent":
            parsed = _parse_ai_agent_log(payload)
            total_cost += parsed.get("total_cost_usd", 0.0)
            items.append(
                {
                    "key": obj["key"],
                    "last_modified": obj["last_modified"].isoformat()
                    if obj.get("last_modified")
                    else "",
                    **parsed,
                }
            )
        elif type == "variants":
            parsed = _parse_variants_log(payload)
            total_cost += parsed.get("total_cost_usd", 0.0)
            items.append(
                {
                    "key": obj["key"],
                    "last_modified": obj["last_modified"].isoformat()
                    if obj.get("last_modified")
                    else "",
                    **parsed,
                }
            )
        elif type == "search":
            parsed = _parse_search_log(payload)
            items.append(
                {
                    "key": obj["key"],
                    "last_modified": obj["last_modified"].isoformat()
                    if obj.get("last_modified")
                    else "",
                    **parsed,
                }
            )
        if limit and len(items) >= limit:
            break

    note = ""
    if truncated:
        note = f"최근 {len(scan_objects)}건 기준 합계입니다."

    return JSONResponse(
        {
            "items": items,
            "total_cost_usd": total_cost if type in {"ai_agent", "variants"} else 0,
            "note": note,
        }
    )


@router.get("/admin/api/logs/detail")
def admin_log_detail(request: Request, key: str) -> JSONResponse:
    if not _require_admin(request):
        raise HTTPException(status_code=403, detail="Unauthorized")
    if not key.startswith("logs/"):
        raise HTTPException(status_code=400, detail="Invalid key")
    allowed = tuple(f"logs/{prefix}" for prefix in _LOG_TYPES.values())
    if not key.startswith(allowed):
        raise HTTPException(status_code=403, detail="Forbidden")
    text, _ = _get_object_text(key)
    try:
        parsed = json.loads(text)
        text = json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return JSONResponse({"content": text})
