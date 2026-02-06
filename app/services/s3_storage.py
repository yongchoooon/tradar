"""S3 image upload + presign helpers."""

from __future__ import annotations

import base64
import io
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from PIL import Image

try:  # pragma: no cover - optional dependency
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:  # pragma: no cover
    boto3 = None
    BotoCoreError = ClientError = Exception  # type: ignore


logger = logging.getLogger(__name__)

DEFAULT_BASE64_MAX_BYTES = 200 * 1024


def _truthy(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _detect_image_format(data: bytes) -> Tuple[str, str]:
    if not data:
        return "jpg", "image/jpeg"
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "JPEG").lower()
    except Exception:
        return "jpg", "image/jpeg"
    if fmt == "jpeg":
        return "jpg", "image/jpeg"
    if fmt == "png":
        return "png", "image/png"
    if fmt == "webp":
        return "webp", "image/webp"
    if fmt == "gif":
        return "gif", "image/gif"
    return "jpg", "image/jpeg"


def _build_key(prefix: str, ext: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    token = uuid.uuid4().hex
    safe_prefix = prefix.strip("/").strip()
    if safe_prefix:
        return f"{safe_prefix}/{timestamp}/{token}.{ext}"
    return f"{timestamp}/{token}.{ext}"


@dataclass(frozen=True)
class ImageTransferError(RuntimeError):
    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class S3UploadError(ImageTransferError):
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


class S3ImageStore:
    def __init__(self) -> None:
        self._bucket = os.getenv("TRADAR_DATA_BUCKET", "tradar-data")
        self._prefix = os.getenv("TRADAR_IMAGE_PREFIX", "queries")
        self._presign_ttl = int(os.getenv("TRADAR_PRESIGN_TTL_SECONDS", "600"))
        self._endpoint_url = os.getenv("TRADAR_S3_ENDPOINT_URL")
        self._region = os.getenv("AWS_REGION")

        if boto3 is None:
            raise RuntimeError("boto3 is not available for S3 uploads")

        self._client = boto3.client(
            "s3", region_name=self._region, endpoint_url=self._endpoint_url
        )

    def upload_and_presign(self, image_bytes: bytes) -> ImageRef:
        if not image_bytes:
            raise ValueError("Empty image payload")
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
        return ImageRef(type="presigned_url", url=url, bucket=self._bucket, key=key)


def _build_base64_ref(image_bytes: bytes, max_inline: int) -> ImageRef:
    if len(image_bytes) > max_inline:
        raise Base64PayloadTooLargeError(
            "Image too large for base64 fallback",
            "IMAGE_TOO_LARGE",
        )
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return ImageRef(type="base64", data=encoded)


def build_image_ref(image_bytes: bytes) -> ImageRef:
    """Prefer S3 presigned URL; base64 fallback only when explicitly enabled."""
    allow_base64 = _truthy(os.getenv("ALLOW_BASE64_FALLBACK", "false"))
    max_inline = int(
        os.getenv("BASE64_MAX_IMAGE_BYTES", str(DEFAULT_BASE64_MAX_BYTES))
    )
    disable_s3 = _truthy(os.getenv("TRADAR_DISABLE_S3"))

    if not disable_s3:
        try:
            store = S3ImageStore()
            return store.upload_and_presign(image_bytes)
        except ClientError as exc:
            error_code = "S3_UPLOAD_FAILED"
            response = getattr(exc, "response", {}) or {}
            s3_code = (response.get("Error") or {}).get("Code")
            if s3_code == "AccessDenied":
                error_code = "S3_UPLOAD_DENIED"
            raise S3UploadError("S3 upload failed", error_code) from exc
        except (BotoCoreError, RuntimeError, ValueError) as exc:
            raise S3UploadError("S3 upload failed", "S3_UPLOAD_FAILED") from exc

    if not allow_base64:
        raise Base64FallbackDisabledError(
            "Image transfer failed (base64 fallback disabled)",
            "IMAGE_TRANSFER_FAILED",
        )

    return _build_base64_ref(image_bytes, max_inline)
