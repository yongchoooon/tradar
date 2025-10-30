"""Catalog accessors backed by PostgreSQL."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote

from app.services import db


REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_BASE_DIR_ENV = os.getenv('IMAGE_BASE_DIR')
IMAGE_BASE_DIR = Path(IMAGE_BASE_DIR_ENV).resolve() if IMAGE_BASE_DIR_ENV else None


@dataclass(frozen=True)
class TrademarkRecord:
    application_number: str
    title_korean: str
    title_english: str
    status: str
    class_codes: List[str]
    goods_services: str
    doi: Optional[str]
    image_path: Optional[str]
    thumb_url: Optional[str]


def bulk_by_ids(ids: Iterable[str]) -> Dict[str, TrademarkRecord]:
    id_list = [tm_id for tm_id in ids if tm_id]
    if not id_list:
        return {}

    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT application_number,
                   COALESCE(title_korean, ''),
                   COALESCE(title_english, ''),
                   COALESCE(status, ''),
                   service_classes,
                   COALESCE(goods_services, ''),
                   doi,
                   image_path
            FROM trademarks
            WHERE application_number = ANY(%s)
            """,
            (id_list,),
        )
        rows = cur.fetchall()

    results: Dict[str, TrademarkRecord] = {}
    for row in rows:
        (
            app_no,
            title_ko,
            title_en,
            status,
            service_classes,
            goods_services,
            doi,
            image_path,
        ) = row
        results[app_no] = TrademarkRecord(
            application_number=app_no,
            title_korean=title_ko or "",
            title_english=title_en or "",
            status=status or "",
            class_codes=_normalize_classes(service_classes),
            goods_services=goods_services or "",
            doi=doi,
            image_path=image_path,
            thumb_url=_resolve_thumb_url(image_path),
        )
    return results


def _normalize_classes(raw) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, list):
        return [str(item).strip() for item in loaded if str(item).strip()]
    if loaded is not None:
        value = str(loaded).strip()
        return [value] if value else []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def _resolve_thumb_url(image_path: str | None) -> Optional[str]:
    if not image_path:
        return None
    image_path = image_path.strip()
    if not image_path:
        return None
    if image_path.startswith(('http://', 'https://')):
        return image_path

    path = Path(image_path)
    candidates = []

    if path.is_absolute():
        candidates.append(path)
    else:
        if IMAGE_BASE_DIR:
            candidates.append(IMAGE_BASE_DIR / path)
        candidates.append(REPO_ROOT / path)
        candidates.append((Path.home() / 'workspace') / path)

    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        if resolved.is_file():
            return f"/media?path={quote(str(resolved))}"
    return None
