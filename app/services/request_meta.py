"""Per-request metadata captured by the API layer."""

from __future__ import annotations

from dataclasses import dataclass
import contextvars
from typing import Optional


@dataclass
class RequestMeta:
    client_id: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None
    origin: Optional[str] = None
    referer: Optional[str] = None
    accept_language: Optional[str] = None


_request_meta_var: contextvars.ContextVar[Optional[RequestMeta]] = contextvars.ContextVar(
    "request_meta", default=None
)


def set_request_meta(meta: RequestMeta) -> contextvars.Token:
    return _request_meta_var.set(meta)


def reset_request_meta(token: contextvars.Token) -> None:
    _request_meta_var.reset(token)


def get_request_meta() -> Optional[RequestMeta]:
    return _request_meta_var.get()
