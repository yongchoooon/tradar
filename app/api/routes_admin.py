"""Lightweight admin routes (single password login)."""

from __future__ import annotations

import hmac
import hashlib
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services import log_storage

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


_LOG_TYPES = {
    "ai_agent": "openai_ai_agent_usage/",
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
      *, *::before, *::after {{ box-sizing: border-box; }}
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
<html lang="ko">
  <head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <title>T-RADAR 관리자</title>
    <style>
      * { box-sizing:border-box; }
      body { font-family: system-ui, sans-serif; background:#f6f8fc; margin:0; padding:2rem; }
      header { display:flex; justify-content:space-between; align-items:center; margin-bottom:1.5rem; }
      h1 { margin:0; }
      .section { background:#fff; padding:1.5rem; border-radius:16px; box-shadow:0 8px 24px rgba(15,23,42,0.08); margin-bottom:1.5rem; }
      .section h2 { margin:0; font-size:1.1rem; }
      .section-header { display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; margin-bottom:0.75rem; }
      .summary { color:#475569; font-size:0.9rem; }
      table { width:100%; border-collapse:collapse; }
      th, td { text-align:left; padding:0.6rem 0.5rem; border-bottom:1px solid #e2e8f0; vertical-align:top; }
      th { color:#64748b; font-size:0.8rem; font-weight:600; text-transform:uppercase; letter-spacing:0.04em; }
      tbody tr:hover { background:#f8fafc; }
      .muted { color:#64748b; font-size:0.85rem; }
      .detail-row td { background:#f8fafc; }
      .detail-box { white-space:pre-wrap; font-size:0.85rem; color:#0f172a; }
      .clickable { cursor:pointer; }
      .sortable { cursor:pointer; user-select:none; }
      .sortable::after { content:""; display:inline-block; margin-left:0.25rem; }
      .narrow { white-space:nowrap; width:1%; }
      a.button { text-decoration:none; padding:0.5rem 0.8rem; border-radius:10px; background:#e2e8f0; color:#0f172a; }
      .badge { display:inline-block; padding:0.2rem 0.5rem; border-radius:999px; background:#e2e8f0; font-size:0.75rem; color:#334155; }
    </style>
  </head>
  <body>
    <header>
      <h1>T-RADAR 관리자</h1>
      <a class="button" href="/admin/logout">로그아웃</a>
    </header>
    <section class="section">
      <div class="section-header">
        <h2>시뮬레이션 AI Agent 로그</h2>
        <div class="summary" id="ai-summary">총 비용 합계: -</div>
      </div>
      <table>
        <thead>
          <tr>
            <th class="sortable narrow" data-table="ai" data-key="last_modified">날짜</th>
            <th class="narrow">run_id</th>
            <th>상표명</th>
            <th>호출 수</th>
            <th>총 비용</th>
            <th>IP</th>
            <th>user_agent</th>
          </tr>
        </thead>
        <tbody id="ai-table">
          <tr><td colspan="7" class="muted">로딩 중...</td></tr>
        </tbody>
      </table>
      <div class="summary muted" id="ai-note"></div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>LLM 유사어 로그</h2>
        <div class="summary" id="variants-summary">총 비용 합계: -</div>
      </div>
      <table>
        <thead>
          <tr>
            <th class="sortable narrow" data-table="variants" data-key="timestamp">시간</th>
            <th>검색어</th>
            <th>모델</th>
            <th>토큰</th>
            <th>총 비용</th>
            <th>IP</th>
          </tr>
        </thead>
        <tbody id="variants-table">
          <tr><td colspan="6" class="muted">로딩 중...</td></tr>
        </tbody>
      </table>
      <div class="summary muted" id="variants-note"></div>
    </section>

    <section class="section">
      <div class="section-header">
        <h2>시뮬레이션 내용 로그</h2>
        <div class="summary muted">행을 클릭하면 상세 내용을 펼칩니다.</div>
      </div>
      <table>
        <thead>
          <tr>
            <th class="sortable narrow" data-table="debug" data-key="last_modified">수정 시간</th>
            <th>run_tag</th>
            <th>출원번호</th>
            <th>파일 종류</th>
            <th>크기</th>
          </tr>
        </thead>
        <tbody id="debug-table">
          <tr><td colspan="5" class="muted">로딩 중...</td></tr>
        </tbody>
      </table>
    </section>

    <script>
      const MAX_ROWS = 30;
      const formatCost = (value) => {
        if (value === null || value === undefined || Number.isNaN(value)) return "-";
        return "$" + Number(value).toFixed(6);
      };
      const formatDate = (value) => {
        if (!value) return "-";
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ko-KR");
      };
      const formatSize = (bytes) => {
        if (!bytes && bytes !== 0) return "-";
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
      };

      const fetchLogs = async (type) => {
        const res = await fetch(`/admin/api/logs?type=${type}`);
        if (!res.ok) {
          const msg = await res.text();
          throw new Error(msg || "Failed to load logs");
        }
        return res.json();
      };

      const state = {
        ai: { items: [], total_cost_usd: 0, sortKey: "last_modified", sortDir: "desc" },
        variants: { items: [], total_cost_usd: 0, sortKey: "timestamp", sortDir: "desc" },
        debug: { items: [], sortKey: "last_modified", sortDir: "desc" },
      };

      const sortItems = (items, key, dir) => {
        const copy = items.slice();
        copy.sort((a, b) => {
          const ta = new Date(a[key] || 0).getTime();
          const tb = new Date(b[key] || 0).getTime();
          const av = Number.isNaN(ta) ? 0 : ta;
          const bv = Number.isNaN(tb) ? 0 : tb;
          return dir === "asc" ? av - bv : bv - av;
        });
        return copy;
      };

      const renderAiAgent = () => {
        const body = document.getElementById("ai-table");
        body.innerHTML = "";
        const items = sortItems(state.ai.items, state.ai.sortKey, state.ai.sortDir).slice(0, MAX_ROWS);
        if (!items.length) {
          body.innerHTML = '<tr><td colspan="7" class="muted">데이터가 없습니다.</td></tr>';
          return;
        }
        items.forEach((item) => {
          const row = document.createElement("tr");
          row.classList.add("clickable");
          row.innerHTML = `
            <td class="narrow">${formatDate(item.last_modified)}</td>
            <td class="narrow">${item.run_id || "-"}</td>
            <td>${item.query_title || "-"}</td>
            <td>${item.total_calls ?? "-"}</td>
            <td>${formatCost(item.total_cost_usd)}</td>
            <td>${item.client_ip || "-"}</td>
            <td>${item.user_agent || "-"}</td>
          `;
          row.addEventListener("click", () => toggleDetail(row, item.key, 7));
          body.appendChild(row);
        });
        document.getElementById("ai-summary").textContent =
          `총 비용 합계: ${formatCost(state.ai.total_cost_usd)}`;
        document.getElementById("ai-note").textContent = state.ai.note || "";
      };

      const renderVariants = () => {
        const body = document.getElementById("variants-table");
        body.innerHTML = "";
        const items = sortItems(state.variants.items, state.variants.sortKey, state.variants.sortDir).slice(0, MAX_ROWS);
        if (!items.length) {
          body.innerHTML = '<tr><td colspan="6" class="muted">데이터가 없습니다.</td></tr>';
          return;
        }
        items.forEach((item) => {
          const row = document.createElement("tr");
          row.innerHTML = `
            <td class="narrow">${formatDate(item.timestamp)}</td>
            <td>${item.query_text || "-"}</td>
            <td>${item.model || "-"}</td>
            <td>${item.total_tokens ?? "-"}</td>
            <td>${formatCost(item.total_cost_usd)}</td>
            <td>${item.client_ip || "-"}</td>
          `;
          body.appendChild(row);
        });
        document.getElementById("variants-summary").textContent =
          `총 비용 합계: ${formatCost(state.variants.total_cost_usd)}`;
        document.getElementById("variants-note").textContent = state.variants.note || "";
      };

      const renderDebug = () => {
        const body = document.getElementById("debug-table");
        body.innerHTML = "";
        const items = sortItems(state.debug.items, state.debug.sortKey, state.debug.sortDir).slice(0, MAX_ROWS);
        if (!items.length) {
          body.innerHTML = '<tr><td colspan="5" class="muted">데이터가 없습니다.</td></tr>';
          return;
        }
        items.forEach((item) => {
          const row = document.createElement("tr");
          row.classList.add("clickable");
          row.innerHTML = `
            <td class="narrow">${formatDate(item.last_modified)}</td>
            <td>${item.run_tag || "-"}</td>
            <td>${item.app_no || "-"}</td>
            <td><span class="badge">${item.file_type || "-"}</span></td>
            <td>${formatSize(item.size)}</td>
          `;
          row.addEventListener("click", () => toggleDetail(row, item.key, 5));
          body.appendChild(row);
        });
      };

      const toggleDetail = async (row, key, colspan) => {
        const next = row.nextElementSibling;
        if (next && next.classList.contains("detail-row")) {
          next.remove();
          return;
        }
        const detailRow = document.createElement("tr");
        detailRow.classList.add("detail-row");
        detailRow.innerHTML = `<td colspan="${colspan}"><div class="detail-box">로딩 중...</div></td>`;
        row.parentNode.insertBefore(detailRow, row.nextSibling);
        try {
          const res = await fetch(`/admin/api/logs/detail?key=${encodeURIComponent(key)}`);
          if (!res.ok) throw new Error(await res.text());
          const payload = await res.json();
          const text = payload.content || "";
          const box = detailRow.querySelector(".detail-box");
          box.textContent = text;
        } catch (err) {
          const box = detailRow.querySelector(".detail-box");
          box.textContent = "상세 내용을 불러오지 못했습니다.";
        }
      };

      const bindSorting = () => {
        document.querySelectorAll(".sortable").forEach((th) => {
          th.addEventListener("click", () => {
            const table = th.dataset.table;
            const key = th.dataset.key;
            if (!table || !key || !state[table]) return;
            const st = state[table];
            if (st.sortKey === key) {
              st.sortDir = st.sortDir === "asc" ? "desc" : "asc";
            } else {
              st.sortKey = key;
              st.sortDir = "desc";
            }
            if (table === "ai") renderAiAgent();
            if (table === "variants") renderVariants();
            if (table === "debug") renderDebug();
          });
        });
      };

      const init = async () => {
        try {
          const data = await fetchLogs("ai_agent");
          state.ai.items = data.items || [];
          state.ai.total_cost_usd = data.total_cost_usd || 0;
          state.ai.note = data.note || "";
          renderAiAgent();
        } catch (err) {
          document.getElementById("ai-table").innerHTML =
            `<tr><td colspan="7" class="muted">불러오기 실패</td></tr>`;
        }
        try {
          const data = await fetchLogs("variants");
          state.variants.items = data.items || [];
          state.variants.total_cost_usd = data.total_cost_usd || 0;
          state.variants.note = data.note || "";
          renderVariants();
        } catch (err) {
          document.getElementById("variants-table").innerHTML =
            `<tr><td colspan="6" class="muted">불러오기 실패</td></tr>`;
        }
        try {
          const data = await fetchLogs("debug");
          state.debug.items = data.items || [];
          renderDebug();
        } catch (err) {
          document.getElementById("debug-table").innerHTML =
            `<tr><td colspan="5" class="muted">불러오기 실패</td></tr>`;
        }
      };

      bindSorting();
      init();
    </script>
  </body>
</html>
"""
    )


@router.get("/admin/api/logs")
def admin_logs(request: Request, type: str) -> JSONResponse:
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

    note = ""
    if truncated:
        note = f"최근 {len(scan_objects)}건 기준 합계입니다."

    return JSONResponse(
        {
            "items": items,
            "total_cost_usd": total_cost,
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
