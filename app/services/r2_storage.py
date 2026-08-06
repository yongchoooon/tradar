"""Cloudflare R2 image upload and presigned URL helpers."""

from __future__ import annotations

import base64
import io
import mimetypes
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from PIL import Image

try:  # pragma: no cover - dependency availability is environment-specific
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:  # pragma: no cover
    BotoCoreError = ClientError = Exception  # type: ignore

from app.services.r2_client import (
    R2ConfigurationError,
    get_r2_client,
    r2_bucket_name,
    r2_enabled,
)


DEFAULT_BASE64_MAX_BYTES = 200 * 1024
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _detect_image_format(data: bytes) -> Tuple[str, str]:
    if not data:
        raise ValueError("Empty image payload")
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").lower()
            img.verify()
    except Exception as exc:
        raise ValueError("Invalid image payload") from exc
    if fmt == "jpeg":
        return "jpg", "image/jpeg"
    if fmt in {"png", "webp", "gif"}:
        return fmt, f"image/{fmt}"
    raise ValueError(f"Unsupported image format: {fmt or 'unknown'}")


def _build_key(prefix: str, ext: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    token = uuid.uuid4().hex
    safe_prefix = prefix.strip("/").strip()
    if safe_prefix:
        return f"{safe_prefix}/{timestamp}/{token}.{ext}"
    return f"{timestamp}/{token}.{ext}"


def validate_r2_presigned_url(url: str) -> None:
    """Reject arbitrary URLs before a desktop worker fetches an image."""

    endpoint = os.getenv("R2_ENDPOINT_URL", "").strip()
    endpoint_host = (urlparse(endpoint).hostname or "").lower()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(
            "image_ref URL must be a Cloudflare R2 presigned HTTPS URL"
        ) from exc
    if (
        parsed.scheme != "https"
        or not endpoint_host
        or not host
        or parsed.username
        or parsed.password
        or (port not in {None, 443})
        or (host != endpoint_host and not host.endswith(f".{endpoint_host}"))
    ):
        raise ValueError("image_ref URL must be a Cloudflare R2 presigned HTTPS URL")


@dataclass(frozen=True)
class ImageTransferError(RuntimeError):
    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class R2UploadError(ImageTransferError):
    pass


class Base64FallbackDisabledError(ImageTransferError):
    pass


class Base64PayloadTooLargeError(ImageTransferError):
    pass


@dataclass(frozen=True)
class ImageRef:
    type: str
    url: Optional[str] = None
    data: Optional[str] = None
    bucket: Optional[str] = None
    key: Optional[str] = None

    def as_payload(self) -> Dict[str, str]:
        payload: Dict[str, str] = {"type": self.type}
        if self.url:
            payload["url"] = self.url
        if self.data:
            payload["data"] = self.data
        return payload


class R2ImageStore:
    def __init__(self) -> None:
        if not r2_enabled():
            raise R2ConfigurationError("R2 is disabled; set R2_ENABLED=true")
        self._bucket = r2_bucket_name()
        self._prefix = os.getenv("R2_IMAGE_PREFIX", "queries")
        self._presign_ttl = int(os.getenv("R2_PRESIGN_TTL_SECONDS", "600"))
        if not 1 <= self._presign_ttl <= 604800:
            raise R2ConfigurationError(
                "R2_PRESIGN_TTL_SECONDS must be between 1 and 604800"
            )
        self._client = get_r2_client()

    def upload_and_presign(self, image_bytes: bytes) -> ImageRef:
        ext, content_type = _detect_image_format(image_bytes)
        key = _build_key(self._prefix, ext)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=image_bytes,
            ContentType=content_type,
        )
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._presign_ttl,
        )
        validate_r2_presigned_url(url)
        return ImageRef(type="presigned_url", url=url, bucket=self._bucket, key=key)

    def presign_upload(self, *, filename: str, content_type: str | None) -> dict:
        if not filename:
            raise ValueError("filename is required")
        normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
        if normalized_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise ValueError(
                "content_type must be one of: "
                + ", ".join(sorted(ALLOWED_IMAGE_CONTENT_TYPES))
            )
        ext = _guess_extension(filename, normalized_type)
        key = _build_key(self._prefix, ext)
        params = {
            "Bucket": self._bucket,
            "Key": key,
            "ContentType": normalized_type,
        }
        upload_url = self._client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=self._presign_ttl,
        )
        read_url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._presign_ttl,
        )
        validate_r2_presigned_url(upload_url)
        validate_r2_presigned_url(read_url)
        return {
            "upload_url": upload_url,
            "read_url": read_url,
            "bucket": self._bucket,
            "key": key,
            "content_type": normalized_type,
        }


def _guess_extension(filename: str, content_type: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "jpeg":
        ext = "jpg"
    allowed_extensions = {"gif", "jpg", "png", "webp"}
    if ext not in allowed_extensions:
        guessed = mimetypes.guess_extension(content_type)
        ext = (guessed or ".bin").lstrip(".")
    return ext


def _build_base64_ref(image_bytes: bytes, max_inline: int) -> ImageRef:
    if len(image_bytes) > max_inline:
        raise Base64PayloadTooLargeError(
            "Image too large for base64 fallback",
            "IMAGE_TOO_LARGE",
        )
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return ImageRef(type="base64", data=encoded)


def build_image_ref(image_bytes: bytes) -> ImageRef:
    """Prefer an R2 presigned URL; use base64 only when explicitly enabled."""

    allow_base64 = _truthy(os.getenv("ALLOW_BASE64_FALLBACK", "false"))
    max_inline = int(
        os.getenv("BASE64_MAX_IMAGE_BYTES", str(DEFAULT_BASE64_MAX_BYTES))
    )

    if r2_enabled():
        try:
            return R2ImageStore().upload_and_presign(image_bytes)
        except ClientError as exc:
            response = getattr(exc, "response", {}) or {}
            r2_code = (response.get("Error") or {}).get("Code")
            error_code = (
                "R2_UPLOAD_DENIED" if r2_code == "AccessDenied" else "R2_UPLOAD_FAILED"
            )
            raise R2UploadError("R2 upload failed", error_code) from exc
        except (BotoCoreError, R2ConfigurationError, RuntimeError, ValueError) as exc:
            raise R2UploadError("R2 upload failed", "R2_UPLOAD_FAILED") from exc

    if not allow_base64:
        raise Base64FallbackDisabledError(
            "Image transfer failed (R2 disabled and base64 fallback disabled)",
            "IMAGE_TRANSFER_FAILED",
        )

    return _build_base64_ref(image_bytes, max_inline)
