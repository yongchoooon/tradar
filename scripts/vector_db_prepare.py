#!/usr/bin/env python
"""Utility to prepare the trademark vector database without Docker.

The script performs three tasks:
1. Ensure the pgvector extension and required tables exist.
2. Load metadata + image assets from a local directory.
3. Generate DINOv2/MetaCLIP2 style embeddings via the repository's embedder
   interfaces and upsert them into PostgreSQL.

Once the data is in place you can immediately issue ANN searches over the
`image_embeddings_*` and `text_embeddings_metaclip` tables.
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
except Exception:  # pragma: no cover - tqdm 
    tqdm = None

if __package__ is None or __package__ == "":  # pragma: no cover - CLI execution path
    sys.path.append(str(Path(__file__).resolve().parents[1]))

import psycopg
from pgvector.psycopg import register_vector

from app.services.image_embed_service import ImageEmbedder
from app.services.text_embed_service import TextEmbedder

# Default DSN matches the docker-compose postgres service we add later.
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/tradar"


@dataclass(slots=True)
class Record:
    application_number: str
    title_korean: str
    title_english: str
    status: str
    service_classes: List[str]
    goods_services: str
    doi: str
    image_path: Path
    image_embedding_dino: List[float]
    image_embedding_metaclip: List[float]
    text_embedding_metaclip: List[float]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare pgvector tables and ingest trademark embeddings."
    )
    parser.add_argument(
        "--metadata",
        required=True,
        type=Path,
        help="Path to metadata file (JSON list or CSV/TSV).",
    )
    parser.add_argument(
        "--images-root",
        type=Path,
        default=Path("."),
        help="Directory prepended to relative image paths in the metadata.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL URL (defaults to DATABASE_URL env or local instance).",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Remove existing embeddings before inserting new ones.",
    )
    parser.add_argument(
        "--image-backend",
        choices=["torch"],
        default=None,
        help="Select embedding backend for images (defaults to env IMAGE_EMBED_BACKEND or torch).",
    )
    parser.add_argument(
        "--text-backend",
        choices=["torch"],
        default=None,
        help="Select embedding backend for text (defaults to env TEXT_EMBED_BACKEND or torch).",
    )
    parser.add_argument(
        "--metaclip-model",
        default=None,
        help="Override MetaCLIP2 model name or local path.",
    )
    parser.add_argument(
        "--dinov2-model",
        default=None,
        help="Override DINOv2 model name or local path.",
    )
    parser.add_argument(
        "--embed-device",
        default=None,
        help="Force embedding device (e.g., cpu, cuda:0).",
    )
    return parser.parse_args(argv)


def load_metadata(path: Path) -> Iterable[dict]:
    ext = path.suffix.lower()
    if ext == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("records", [])
        if not isinstance(data, list):
            raise ValueError("JSON metadata must be a list of objects")
        return data
    if ext in {".csv", ".tsv"}:
        import csv

        delimiter = "," if ext == ".csv" else "\t"
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            return list(reader)
    raise ValueError(f"Unsupported metadata format: {path}")


def normalize_service_classes(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    # Support comma/pipe/semicolon separated inputs.
    for sep in ("|", ";", ","):
        if sep in text:
            return [part.strip() for part in text.split(sep) if part.strip()]
    return [text]


def coalesce(*choices: object, default: str = "") -> str:
    for choice in choices:
        if choice is None:
            continue
        text = str(choice).strip()
        if text:
            return text
    return default


def build_records(
    raw_items: Iterable[dict],
    images_root: Path,
    image_backend: str | None = None,
    text_backend: str | None = None,
) -> List[Record]:
    image_embedder = ImageEmbedder(image_backend)
    text_embedder = TextEmbedder(text_backend)

    source_items = list(raw_items)
    records: List[Record] = []
    batch_size = int(os.getenv("VECTOR_DB_BATCH_SIZE", "64"))
    total_items = len(source_items)
    iterator = (
        tqdm(range(0, total_items, batch_size), desc="Embedding trademarks", unit="item")
        if tqdm
        else range(0, total_items, batch_size)
    )

    for start in iterator:
        chunk = source_items[start : start + batch_size]
        application_numbers: List[str] = []
        title_ko_batch: List[str] = []
        title_en_batch: List[str] = []
        status_batch: List[str] = []
        classes_batch: List[List[str]] = []
        goods_batch: List[str] = []
        doi_batch: List[str] = []
        image_paths: List[Path] = []
        text_groups: List[List[str]] = []

        for item in chunk:
            application_number = coalesce(
                item.get("application_number"),
                item.get("trademark_id"),
                item.get("id"),
                default="",
            )
            if not application_number:
                raise ValueError("Metadata entry is missing 'application_number'")

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

            image_path: Path | None = None
            for candidate in image_candidates:
                candidate_path = Path(candidate)
                if not candidate_path.is_absolute():
                    candidate_path = (images_root / candidate_path).resolve()
                else:
                    candidate_path = candidate_path.resolve()
                if candidate_path.exists():
                    image_path = candidate_path
                    break

            if image_path is None:
                raise FileNotFoundError(
                    f"{application_number}: image not found -> {image_candidates or '[missing]'}"
                )
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
            goods_field = item.get("goods_services")
            if not goods_field:
                goods_field = item.get("goods_services_descriptions")
            if isinstance(goods_field, list):
                goods = "; ".join(
                    str(part).strip() for part in goods_field if str(part).strip()
                )
            else:
                goods = coalesce(goods_field, item.get("goods"), default="")

            service_classes_raw = item.get("service_classes")
            if not service_classes_raw:
                service_classes_raw = item.get("class_numbers")
            normalized_classes = normalize_service_classes(service_classes_raw)

            doi = coalesce(item.get("doi"), item.get("DOI"), default="")

            application_numbers.append(application_number)
            title_ko_batch.append(title_korean)
            title_en_batch.append(title_english)
            status_batch.append(coalesce(item.get("status"), default="출원"))
            classes_batch.append(normalized_classes)
            goods_batch.append(goods)
            doi_batch.append(doi)
            image_paths.append(image_path)
            text_groups.append([title_korean, title_english])

        image_bytes_batch = [path.read_bytes() for path in image_paths]
        image_vectors_batch = image_embedder.encode_batch(image_bytes_batch)
        text_vectors_batch = text_embedder.encode_many_batch(text_groups)

        if len(image_vectors_batch) != len(application_numbers):
            raise RuntimeError(
                "Image batch size mismatch. Expected "
                f"{len(application_numbers)} got {len(image_vectors_batch)}"
            )
        if len(text_vectors_batch) != len(application_numbers):
            text_vectors_batch = [
                text_embedder.encode_many(group) for group in text_groups
            ]

        for idx, application_number in enumerate(application_numbers):
            image_vectors = image_vectors_batch[idx]
            text_vectors = (
                text_vectors_batch[idx]
                if idx < len(text_vectors_batch)
                else text_embedder.encode_many(text_groups[idx])
            )
            record = Record(
                application_number=application_number,
                title_korean=title_ko_batch[idx],
                title_english=title_en_batch[idx],
                status=status_batch[idx],
                service_classes=classes_batch[idx],
                goods_services=goods_batch[idx],
                doi=doi_batch[idx],
                image_path=image_paths[idx],
                image_embedding_dino=list(image_vectors["dino"]),
                image_embedding_metaclip=list(image_vectors["metaclip"]),
                text_embedding_metaclip=list(text_vectors),
            )
            records.append(record)
    if not records:
        raise ValueError("No valid metadata rows found.")
    return records


def create_schema(conn: psycopg.Connection, records: Sequence[Record]) -> None:
    dino_dim = len(records[0].image_embedding_dino)
    metaclip_dim = len(records[0].image_embedding_metaclip)
    text_dim = len(records[0].text_embedding_metaclip)
    min_dim = int(os.getenv("VECTOR_DB_MIN_DIM", "32"))
    if dino_dim < min_dim or metaclip_dim < min_dim or text_dim < min_dim:
        raise RuntimeError(
            "Embedding dimension is unexpectedly small. Only torch-based "
            "embeddings are supported; check IMAGE/TEXT_EMBED_BACKEND settings."
        )
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
            CREATE TABLE IF NOT EXISTS image_embeddings_dino (
                application_number TEXT PRIMARY KEY REFERENCES trademarks(application_number) ON DELETE CASCADE,
                vector vector({dino_dim})
            );
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS image_embeddings_metaclip (
                application_number TEXT PRIMARY KEY REFERENCES trademarks(application_number) ON DELETE CASCADE,
                vector vector({metaclip_dim})
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
        # Vector indexes accelerate ANN similarity lookups.
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
            CREATE INDEX IF NOT EXISTS idx_image_embeddings_dino_vector
                ON image_embeddings_dino
                USING ivfflat (vector vector_cosine_ops) WITH (lists = 100);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_image_embeddings_metaclip_vector
                ON image_embeddings_metaclip
                USING ivfflat (vector vector_cosine_ops) WITH (lists = 100);
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


def drop_tables(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS image_embeddings_dino CASCADE;")
        cur.execute("DROP TABLE IF EXISTS image_embeddings_metaclip CASCADE;")
        cur.execute("DROP TABLE IF EXISTS text_embeddings_metaclip CASCADE;")
        cur.execute("DROP TABLE IF EXISTS trademarks CASCADE;")
    conn.commit()


def upsert_records(conn: psycopg.Connection, records: Sequence[Record]) -> None:
    iterable = list(records)
    iterator = tqdm(iterable, desc="Upserting records", unit="item") if tqdm else iterable
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
                    image_path = EXCLUDED.image_path,
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
                    "image_path": str(rec.image_path),
                },
            )
            cur.execute(
                """
                INSERT INTO image_embeddings_dino (application_number, vector)
                VALUES (%(id)s, %(vector)s)
                ON CONFLICT (application_number)
                DO UPDATE SET vector = EXCLUDED.vector;
                """,
                {"id": rec.application_number, "vector": rec.image_embedding_dino},
            )
            cur.execute(
                """
                INSERT INTO image_embeddings_metaclip (application_number, vector)
                VALUES (%(id)s, %(vector)s)
                ON CONFLICT (application_number)
                DO UPDATE SET vector = EXCLUDED.vector;
                """,
                {"id": rec.application_number, "vector": rec.image_embedding_metaclip},
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
    if args.image_backend:
        os.environ["IMAGE_EMBED_BACKEND"] = args.image_backend
    if args.text_backend:
        os.environ["TEXT_EMBED_BACKEND"] = args.text_backend
    if args.metaclip_model:
        os.environ["METACLIP_MODEL_NAME"] = args.metaclip_model
    if args.dinov2_model:
        os.environ["DINOV2_MODEL_NAME"] = args.dinov2_model
    if args.embed_device:
        os.environ["EMBED_DEVICE"] = args.embed_device

    records = build_records(raw_items, args.images_root, args.image_backend, args.text_backend)
    database_url = args.database_url

    print(f"[vector-db] Connecting to {database_url}")
    with psycopg.connect(database_url) as conn:
        register_vector(conn)
        if args.truncate:
            print("[vector-db] Dropping existing tables")
            drop_tables(conn)
        print("[vector-db] Ensuring schema")
        create_schema(conn, records)
        print(f"[vector-db] Inserting {len(records)} records")
        upsert_records(conn, records)

    print("[vector-db] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
