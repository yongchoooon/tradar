from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.services import r2_client
from app.services.r2_storage import (
    R2ImageStore,
    R2UploadError,
    build_image_ref,
    validate_r2_presigned_url,
)


class FakeR2Client:
    def __init__(self) -> None:
        self.puts = []
        self.presigns = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.presigns.append((operation, Params, ExpiresIn))
        return (
            "https://account.r2.cloudflarestorage.com/"
            f"{operation}/{Params['Key']}"
        )


@pytest.fixture
def configured_r2(monkeypatch):
    values = {
        "R2_ENABLED": "true",
        "R2_BUCKET": "tradar-test",
        "R2_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
        "R2_ACCESS_KEY_ID": "test-access-key",
        "R2_SECRET_ACCESS_KEY": "test-secret-key",
        "R2_REGION": "auto",
        "R2_IMAGE_PREFIX": "queries",
        "R2_PRESIGN_TTL_SECONDS": "600",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    fake = FakeR2Client()
    monkeypatch.setattr("app.services.r2_storage.get_r2_client", lambda: fake)
    r2_client.clear_r2_client_cache()
    yield fake
    r2_client.clear_r2_client_cache()


def test_presign_upload_uses_r2_bucket_and_content_type(configured_r2) -> None:
    result = R2ImageStore().presign_upload(
        filename="mark.png",
        content_type="image/png",
    )

    assert result["bucket"] == "tradar-test"
    assert result["content_type"] == "image/png"
    assert result["key"].startswith("queries/")
    assert result["key"].endswith(".png")
    assert [call[0] for call in configured_r2.presigns] == [
        "put_object",
        "get_object",
    ]


def test_presign_upload_rejects_non_image_content_type(configured_r2) -> None:
    with pytest.raises(ValueError, match="content_type"):
        R2ImageStore().presign_upload(
            filename="payload.txt",
            content_type="text/plain",
        )


def test_build_image_ref_uploads_valid_image_to_r2(configured_r2) -> None:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color="white").save(buffer, format="PNG")

    ref = build_image_ref(buffer.getvalue())

    assert ref.type == "presigned_url"
    assert ref.bucket == "tradar-test"
    assert ref.key and ref.key.endswith(".png")
    assert configured_r2.puts[0]["ContentType"] == "image/png"


def test_build_image_ref_rejects_invalid_image(configured_r2) -> None:
    with pytest.raises(R2UploadError) as exc_info:
        build_image_ref(b"not-an-image")
    assert exc_info.value.error_code == "R2_UPLOAD_FAILED"


def test_validate_r2_presigned_url_rejects_arbitrary_hosts(configured_r2) -> None:
    validate_r2_presigned_url(
        "https://account.r2.cloudflarestorage.com/tradar-test/object?signature=test"
    )
    validate_r2_presigned_url(
        "https://tradar-test.account.r2.cloudflarestorage.com/object?signature=test"
    )

    with pytest.raises(ValueError, match="R2 presigned"):
        validate_r2_presigned_url("http://127.0.0.1:9200/_cluster/health")
