#!/usr/bin/env python3
"""Check the configured Cloudflare R2 bucket without printing credentials."""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.r2_client import (  # noqa: E402
    get_r2_client,
    r2_bucket_name,
    r2_enabled,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        default=".env.runtime",
        help="Environment file to load (default: .env.runtime)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Also upload, download, and delete a small health-check object",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env_path = Path(args.env_file)
    if not env_path.is_file():
        print(f"ERROR: environment file not found: {env_path}", file=sys.stderr)
        return 2
    load_dotenv(env_path, override=False)

    if not r2_enabled():
        print("ERROR: R2_ENABLED must be true", file=sys.stderr)
        return 2

    bucket = r2_bucket_name()
    endpoint_host = urlparse(os.environ.get("R2_ENDPOINT_URL", "")).hostname
    client = get_r2_client()

    print(f"Checking bucket={bucket} endpoint={endpoint_host or '<invalid>'}")
    client.list_objects_v2(Bucket=bucket, MaxKeys=1)
    print("OK: list_objects_v2")

    if args.write:
        key = f"_healthchecks/{uuid.uuid4().hex}.txt"
        body = b"tradar-r2-healthcheck\n"
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType="text/plain",
            )
            response = client.get_object(Bucket=bucket, Key=key)
            downloaded = response["Body"].read()
            if downloaded != body:
                raise RuntimeError("R2 health-check content did not match")
            print("OK: put_object/get_object")
        finally:
            client.delete_object(Bucket=bucket, Key=key)
        print("OK: delete_object")

    print("R2 verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
