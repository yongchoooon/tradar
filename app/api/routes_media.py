"""Serve local image files via controlled media endpoint."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import FileResponse

from app.services.r2_client import R2ConfigurationError
from app.services.r2_storage import R2ImageStore, R2UploadError

logger = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_ROOTS = [Path("/home/work/workspace").resolve()]
_DEFAULT_EXTRA_ROOTS = [
    Path.home() / "workspace/tradar-data",
    Path.home() / "workspace/tradar",
]
for base in _DEFAULT_EXTRA_ROOTS:
    try:
        resolved = base.resolve()
    except FileNotFoundError:
        continue
    if resolved.exists():
        _ALLOWED_ROOTS.append(resolved)

extra_env = os.getenv("MEDIA_ALLOWED_ROOTS")
if extra_env:
    for piece in extra_env.split(":"):
        piece = piece.strip()
        if not piece:
            continue
        try:
            resolved = Path(piece).expanduser().resolve()
        except (OSError, FileNotFoundError):
            continue
        if resolved.exists():
            _ALLOWED_ROOTS.append(resolved)

# de-duplicate while preserving order
_seen = []
for root in _ALLOWED_ROOTS:
    if root not in _seen:
        _seen.append(root)
_ALLOWED_ROOTS = _seen


@router.get("/media")
def get_media(path: str = Query(..., description="Absolute file path")) -> FileResponse:
    raw = unquote(path)
    target = Path(raw).resolve()
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    for root in _ALLOWED_ROOTS:
        try:
            target.relative_to(root)
            break
        except ValueError:
            continue
    else:
        raise HTTPException(status_code=403, detail="Access to path denied")

    return FileResponse(target)


class PresignRequest(BaseModel):
    filename: str
    content_type: str | None = None


@router.post("/media/presign")
def presign_upload(req: PresignRequest):
    try:
        store = R2ImageStore()
        return store.presign_upload(
            filename=req.filename,
            content_type=req.content_type,
        )
    except R2UploadError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": exc.error_code, "message": str(exc)},
        ) from exc
    except R2ConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "R2_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_UPLOAD", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "R2_UPLOAD_FAILED", "message": str(exc)},
        ) from exc
