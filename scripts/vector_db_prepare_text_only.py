#!/usr/bin/env python
"""Prepare text-only embeddings for the trademark database.

This helper ingests metadata rows, generates MetaCLIP2 text embeddings, and
upserts just the `trademarks` and `text_embeddings_metaclip` tables. Image
embeddings are deliberately skipped so that existing DINO/MetaCLIP image
vectors remain untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

try:  # Optional progress bar dependency
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover - tqdm optional
    tqdm = None

if __package__ is None or __package__ == "":  # pragma: no cover - CLI execution path
    sys.path.append(str(Path(__file__).resolve().parents[1]))

import psycopg
from pgvector.psycopg import register_vector

from app.services.text_embed_service import TextEmbedder
from scripts.vector_db_prepare import (  # type: ignore
    coalesce,
    load_metadata,
    normalize_service_classes,
)

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/tradar"


@dataclass(slots=True)
class TextRecord:
    application_number: str
    title_korean: str
    title_english: str
    status: str
    service_classes: List[str]
    goods_services: str
    doi: str
    image_path: str | None
    text_embedding_metaclip: List[float]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest MetaCLIP text embeddings without touching image tables.",
    )
    parser.add_argument(
        "--metadata",
        required=True,
        type=Path,
        help="Path to metadata JSON/CSV/TSV (see vector_db_prepare for schema).",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing rows from trademarks/text_embeddings_metaclip before ingesting.",
    )
    parser.add_argument(
        "--text-backend",
        choices=["torch"],
        default=None,
        help="Embedding backend override (defaults to TEXT_EMBED_BACKEND env).",
    )
    parser.add_argument(
        "--metaclip-model",
        default=None,
        help="Optional MetaCLIP model name or path override.",
    )
    parser.add_argument(
        "--embed-device",
        default=None,
        help="Force embedding device (e.g. cpu, cuda:0).",
    )
    return parser.parse_args(argv)


def build_records(
    raw_items: Iterable[dict],
    text_backend: str | None = None,
) -> List[TextRecord]:
    text_embedder = TextEmbedder(text_backend)
    source_items = list(raw_items)
    if not source_items:
        raise ValueError("Metadata file contained no rows.")

    batch_size = int(os.getenv("VECTOR_DB_BATCH_SIZE", "128"))
    records: List[TextRecord] = []
    iterator = (
        tqdm(
            range(0, len(source_items), batch_size),
            desc="Embedding text"
        )
        if tqdm
        else range(0, len(source_items), batch_size)
    )

    for start in iterator:
        chunk = source_items[start : start + batch_size]
        text_groups: List[List[str]] = []
        metadata_rows: List[dict] = []

        for item in chunk:
            application_number = coalesce(
                item.get("application_number"),
                item.get("trademark_id"),
                item.get("id"),
                default="",
            )
            if not application_number:
                raise ValueError("Metadata entry is missing 'application_number'")

            title_korean = coalesce(
                item.get("title_korean"),
                item.get("trademark_title_korean"),
                item.get("title"),
                default="",
            ) or application_number
            title_english = coalesce(
                item.get("title_english"),
                item.get("trademark_title_english"),
                default="",
            )
            goods_field = item.get("goods_services") or item.get("goods_services_descriptions")
            if isinstance(goods_field, list):
                goods_services = "; ".join(
                    str(part).strip() for part in goods_field if str(part).strip()
                )
            else:
                goods_services = coalesce(goods_field, item.get("goods"), default="")

            classes = normalize_service_classes(
                item.get("service_classes") or item.get("class_numbers")
            )
            doi = coalesce(item.get("doi"), item.get("DOI"), default="")
            status = coalesce(item.get("status"), default="출원")

            image_candidates: List[str] = []
            primaries = coalesce(
                item.get("image"),
                item.get("image_path"),
                item.get("filename"),
                default="",
            )
            if primaries:
                image_candidates.append(primaries)
            for key in ("image_paths", "mark_image_paths"):
                value = item.get(key)
                if isinstance(value, list):
                    image_candidates.extend(str(entry).strip() for entry in value if str(entry).strip())
                elif isinstance(value, str) and value.strip():
                    image_candidates.append(value.strip())

            image_path = next((candidate for candidate in image_candidates if candidate), None)

            metadata_rows.append(
                {
                    "application_number": application_number,
                    "title_korean": title_korean,
                    "title_english": title_english,
                    "status": status,
                    "service_classes": classes,
                    "goods_services": goods_services,
                    "doi": doi,
                    "image_path": image_path,
                }
            )
            text_groups.append([title_korean, title_english])

        embeddings = text_embedder.encode_many_batch(text_groups)
        if len(embeddings) != len(metadata_rows):
            raise RuntimeError("Text embedding batch size mismatch.")

        for meta, vector in zip(metadata_rows, embeddings, strict=True):
            records.append(
                TextRecord(
                    application_number=meta["application_number"],
                    title_korean=meta["title_korean"],
                    title_english=meta["title_english"],
                    status=meta["status"],
                    service_classes=meta["service_classes"],
                    goods_services=meta["goods_services"],
                    doi=meta["doi"],
                    image_path=meta["image_path"],
                    text_embedding_metaclip=list(vector),
                )
            )

    return records


def ensure_schema(conn: psycopg.Connection, records: Sequence[TextRecord]) -> None:
    text_dim = len(records[0].text_embedding_metaclip)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trademarks (
                application_number TEXT PRIMARY KEY,
                title_korean TEXT NOT NULL,
                title_english TEXT,
                status TEXT,
                service_classes JSONB DEFAULT '[]'::jsonb,
                goods_services TEXT,
                doi TEXT,
                image_path TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS text_embeddings_metaclip (
                application_number TEXT PRIMARY KEY REFERENCES trademarks(application_number) ON DELETE CASCADE,
                vector vector({text_dim})
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trademarks_status
                ON trademarks (status);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trademarks_service_classes
                ON trademarks USING GIN ((service_classes));
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_text_embeddings_metaclip_vector
                ON text_embeddings_metaclip
                USING ivfflat (vector vector_cosine_ops) WITH (lists = 100);
            """
        )
    conn.commit()


def truncate_tables(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM text_embeddings_metaclip;")
        cur.execute("DELETE FROM trademarks;")
    conn.commit()


def upsert_records(conn: psycopg.Connection, records: Sequence[TextRecord]) -> None:
    iterable = list(records)
    iterator = tqdm(iterable, desc="Upserting records") if tqdm else iterable
    with conn.cursor() as cur:
        for rec in iterator:
            cur.execute(
                """
                INSERT INTO trademarks (application_number, title_korean, title_english, status,
                                        service_classes, goods_services, doi, image_path, updated_at)
                VALUES (%(id)s, %(title_ko)s, %(title_en)s, %(status)s,
                        %(classes)s, %(goods)s, %(doi)s, %(image_path)s, NOW())
                ON CONFLICT (application_number)
                DO UPDATE SET
                    title_korean = EXCLUDED.title_korean,
                    title_english = EXCLUDED.title_english,
                    status = EXCLUDED.status,
                    service_classes = EXCLUDED.service_classes,
                    goods_services = EXCLUDED.goods_services,
                    doi = EXCLUDED.doi,
                    image_path = COALESCE(EXCLUDED.image_path, trademarks.image_path),
                    updated_at = NOW();
                """,
                {
                    "id": rec.application_number,
                    "title_ko": rec.title_korean,
                    "title_en": rec.title_english,
                    "status": rec.status,
                    "classes": json.dumps(rec.service_classes),
                    "goods": rec.goods_services,
                    "doi": rec.doi,
                    "image_path": rec.image_path,
                },
            )
            cur.execute(
                """
                INSERT INTO text_embeddings_metaclip (application_number, vector)
                VALUES (%(id)s, %(vector)s)
                ON CONFLICT (application_number)
                DO UPDATE SET vector = EXCLUDED.vector;
                """,
                {"id": rec.application_number, "vector": rec.text_embedding_metaclip},
            )
    conn.commit()


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    raw_items = load_metadata(args.metadata)

    if args.text_backend:
        os.environ["TEXT_EMBED_BACKEND"] = args.text_backend
    if args.metaclip_model:
        os.environ["METACLIP_MODEL_NAME"] = args.metaclip_model
    if args.embed_device:
        os.environ["EMBED_DEVICE"] = args.embed_device

    records = build_records(raw_items, args.text_backend)
    database_url = args.database_url

    print(f"[text-vector-db] Connecting to {database_url}")
    with psycopg.connect(database_url) as conn:
        register_vector(conn)
        if args.truncate:
            print("[text-vector-db] Clearing trademarks and text embeddings")
            truncate_tables(conn)
        print("[text-vector-db] Ensuring schema")
        ensure_schema(conn, records)
        print(f"[text-vector-db] Upserting {len(records)} records")
        upsert_records(conn, records)

    print("[text-vector-db] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
