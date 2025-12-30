#!/usr/bin/env python
"""Evaluate recall using labelled x → y_list trademark groups."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

try:  # pragma: no cover - optional dependency guard
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover
    def tqdm(iterable, **kwargs):  # type: ignore
        return iterable

from app.pipelines.search_pipeline import SearchPipeline
from app.schemas.search import DebugInfo, DebugRow, ImageBlendDebugRow, SearchRequest

RankRow = Union[DebugRow, ImageBlendDebugRow]

# Ensure psycopg connections have a fallback when the user hasn't exported it.
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/tradar"
DEFAULT_EMBED_DEVICE = "cuda:0"
DEFAULT_IMAGE_EMBED_BACKEND = "torch"
DEFAULT_TEXT_EMBED_BACKEND = "torch"
DEFAULT_METACLIP_MODEL_NAME = "/home/work/workspace/models/metaclip"
DEFAULT_DINOV2_MODEL_NAME = "/home/work/workspace/models/dinov2"
DEFAULT_MEDIA_ALLOWED_ROOTS = "/home/work/workspace/tradar-data:/home/work/workspace/tradar"

os.environ.setdefault("DATABASE_URL", DEFAULT_DATABASE_URL)
os.environ.setdefault("EMBED_DEVICE", DEFAULT_EMBED_DEVICE)
os.environ.setdefault("IMAGE_EMBED_BACKEND", DEFAULT_IMAGE_EMBED_BACKEND)
os.environ.setdefault("TEXT_EMBED_BACKEND", DEFAULT_TEXT_EMBED_BACKEND)
os.environ.setdefault("METACLIP_MODEL_NAME", DEFAULT_METACLIP_MODEL_NAME)
os.environ.setdefault("DINOV2_MODEL_NAME", DEFAULT_DINOV2_MODEL_NAME)
os.environ.setdefault("MEDIA_ALLOWED_ROOTS", DEFAULT_MEDIA_ALLOWED_ROOTS)


def load_pairs(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON must contain a list of entries")
    return data


def choose_text(entry: dict) -> str:
    title_ko = (entry.get("title_korean") or "").strip()
    title_en = (entry.get("title_english") or "").strip()
    if title_ko:
        return title_ko
    if title_en:
        return title_en
    return " "  # return a single space to avoid empty-text pipeline errors


def build_rank_map(rows: Iterable[RankRow]) -> Dict[str, int]:
    return {row.application_number: row.rank for row in rows}


def best_rank_from_targets(
    rank_map: Dict[str, int], targets: Sequence[str]
) -> Tuple[Optional[int], Optional[str]]:
    best_rank: Optional[int] = None
    best_target: Optional[str] = None
    for target in targets:
        rank = rank_map.get(target)
        if isinstance(rank, int) and rank > 0:
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_target = target
    return best_rank, best_target


def best_union_candidate(
    candidates: Sequence[Tuple[str, Optional[int], Optional[str]]]
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    best_rank: Optional[int] = None
    best_app: Optional[str] = None
    best_source: Optional[str] = None
    for source, rank, app in candidates:
        if isinstance(rank, int) and rank > 0:
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_app = app
                best_source = source
    return best_rank, best_app, best_source


def compute_metrics(records: List[dict], metric_names: List[str], ks: List[int]) -> Dict[str, Dict[str, float]]:
    summary: Dict[str, Dict[str, float]] = {}
    total = len(records)
    for metric in metric_names:
        ranks = [rec.get(metric) for rec in records]
        recalls: Dict[str, float] = {}
        valid = [r for r in ranks if isinstance(r, int) and r > 0]
        for k in ks:
            count = sum(1 for r in valid if r <= k)
            recalls[f"recall@{k}"] = count / total if total else 0.0
        mrr = sum(1.0 / r for r in valid) / total if total else 0.0
        recalls["mrr"] = mrr
        recalls["hit_rate"] = len(valid) / total if total else 0.0
        summary[metric] = recalls
    return summary


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def serialize_results(results: Sequence[object]) -> List[dict]:
    return [asdict(result) for result in results]


def serialize_debug_info(debug: DebugInfo) -> dict:
    return {
        "messages": list(debug.messages),
        "image_dino": [asdict(row) for row in debug.image_dino],
        "image_metaclip": [asdict(row) for row in debug.image_metaclip],
        "text_metaclip": [asdict(row) for row in debug.text_metaclip],
        "text_bm25": [asdict(row) for row in debug.text_bm25],
        "image_blended": [asdict(row) for row in debug.image_blended],
        "text_ranked": [asdict(row) for row in debug.text_ranked],
    }


def dump_debug_record(
    dump_dir: Optional[Path],
    *,
    idx: int,
    x_entry: dict,
    targets: Sequence[str],
    request_text: str,
    response,
    debug: DebugInfo,
    row_snapshot: dict,
) -> None:
    if not dump_dir:
        return
    ensure_dir(dump_dir)
    payload = {
        "pair_index": idx,
        "x": x_entry,
        "targets": list(targets),
        "request_text": request_text,
        "query": asdict(response.query),
        "image_top": serialize_results(response.image_top),
        "text_top": serialize_results(response.text_top),
        "image_misc": serialize_results(response.image_misc),
        "text_misc": serialize_results(response.text_misc),
        "debug": serialize_debug_info(debug),
        "row_snapshot": row_snapshot,
    }
    dump_path = dump_dir / f"pair_{idx:05d}_{row_snapshot.get('x_application_number','unknown')}.json"
    dump_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate trademark search recall with x → y_list ground-truth labels."
    )
    parser.add_argument(
        "--pairs-json",
        type=Path,
        default=Path("published_similar_pair_data_i_have_appearance_similarity_2125.json"),
        help="Path to the JSON file containing x/y_list records.",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=None,
        help="Optional cap on how many x→y_list entries to evaluate (useful for quick debugging).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evaluation"),
        help="Directory to store evaluation outputs.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=100,
        help=(
            "Top-K size requested from the pipeline. Set this to the 최대 K you want to "
            "evaluate (default: 100)."
        ),
    )
    parser.add_argument(
        "--experiment-name",
        type=str,
        default="",
        help="Optional experiment name prefix for result files.",
    )
    parser.add_argument(
        "--ks",
        type=int,
        nargs="*",
        default=[1, 5, 10, 20, 50, 100],
        help="List of K values for recall metrics (모두 계산).",
    )
    parser.add_argument(
        "--debug-dump-dir",
        type=Path,
        default=None,
        help="If set, saves per-pair search/top results into this directory for inspection.",
    )

    args = parser.parse_args()

    pairs = load_pairs(args.pairs_json)
    if args.max_pairs is not None and args.max_pairs > 0:
        pairs = pairs[: args.max_pairs]
    ensure_dir(args.output_dir)

    dump_dir: Optional[Path] = None
    if args.debug_dump_dir:
        dump_dir = args.debug_dump_dir
        if not dump_dir.is_absolute():
            dump_dir = args.output_dir / dump_dir
        ensure_dir(dump_dir)

    pipeline = SearchPipeline()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    exp_prefix = args.experiment_name.strip().replace(" ", "_")
    if exp_prefix:
        exp_prefix = f"{exp_prefix}_"
    results_path = args.output_dir / f"{exp_prefix}similar_ylist_eval_{timestamp}.csv"
    summary_path = args.output_dir / f"{exp_prefix}similar_ylist_eval_{timestamp}_summary.json"

    fieldnames = [
        "index",
        "x_application_number",
        "target_y_count",
        "target_y_application_numbers",
        "image_blended_rank",
        "image_blended_match",
        "image_dino_rank",
        "image_dino_match",
        "image_metaclip_rank",
        "image_metaclip_match",
        "text_metaclip_rank",
        "text_metaclip_match",
        "text_ranked_rank",
        "text_ranked_match",
        "bm25_rank",
        "bm25_match",
        "image_union_rank",
        "image_union_match",
        "image_union_source",
        "text_union_rank",
        "text_union_match",
        "text_union_source",
        "overall_union_rank",
        "overall_union_match",
        "overall_union_source",
        "error",
    ]

    records: List[dict] = []

    with results_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for idx, pair in enumerate(tqdm(pairs, desc="Evaluating"), start=1):
            x = pair.get("x", {})
            y_list = pair.get("y_list") or []
            targets = [entry.get("application_number") for entry in y_list if entry.get("application_number")]

            row = {
                "index": idx,
                "x_application_number": x.get("application_number"),
                "target_y_count": len(targets),
                "target_y_application_numbers": ";".join(targets),
                "image_blended_rank": None,
                "image_blended_match": None,
                "image_dino_rank": None,
                "image_dino_match": None,
                "image_metaclip_rank": None,
                "image_metaclip_match": None,
                "text_metaclip_rank": None,
                "text_metaclip_match": None,
                "text_ranked_rank": None,
                "text_ranked_match": None,
                "bm25_rank": None,
                "bm25_match": None,
                "image_union_rank": None,
                "image_union_match": None,
                "image_union_source": None,
                "text_union_rank": None,
                "text_union_match": None,
                "text_union_source": None,
                "overall_union_rank": None,
                "overall_union_match": None,
                "overall_union_source": None,
                "error": None,
            }

            if not targets:
                row["error"] = "empty_y_list"
                writer.writerow(row)
                records.append(row)
                continue

            image_path = x.get("image_path")
            if not image_path:
                row["error"] = "missing_image_path"
                writer.writerow(row)
                records.append(row)
                continue

            try:
                image_bytes = Path(image_path).read_bytes()
            except Exception as exc:
                row["error"] = f"image_read_error: {exc}"
                writer.writerow(row)
                records.append(row)
                continue

            text = choose_text(x)
            request = SearchRequest(
                image_b64=base64.b64encode(image_bytes).decode("utf-8"),
                text=text,
                goods_classes=x.get("service_classes", []),
                k=args.k,
                debug=True,
            )

            try:
                response = pipeline.search(request)
            except Exception as exc:
                row["error"] = f"search_error: {exc}"
                writer.writerow(row)
                records.append(row)
                continue

            debug: Optional[DebugInfo] = response.debug
            if not debug:
                row["error"] = "missing_debug"
                writer.writerow(row)
                records.append(row)
                continue

            image_blended_map = build_rank_map(debug.image_blended)
            image_dino_map = build_rank_map(debug.image_dino)
            image_metaclip_map = build_rank_map(debug.image_metaclip)
            text_metaclip_map = build_rank_map(debug.text_metaclip)
            text_ranked_map = build_rank_map(debug.text_ranked)
            bm25_map = build_rank_map(debug.text_bm25)

            (
                row["image_blended_rank"],
                row["image_blended_match"],
            ) = best_rank_from_targets(image_blended_map, targets)
            row["image_dino_rank"], row["image_dino_match"] = best_rank_from_targets(
                image_dino_map, targets
            )
            (
                row["image_metaclip_rank"],
                row["image_metaclip_match"],
            ) = best_rank_from_targets(image_metaclip_map, targets)
            (
                row["text_metaclip_rank"],
                row["text_metaclip_match"],
            ) = best_rank_from_targets(text_metaclip_map, targets)
            row["text_ranked_rank"], row["text_ranked_match"] = best_rank_from_targets(
                text_ranked_map, targets
            )
            row["bm25_rank"], row["bm25_match"] = best_rank_from_targets(bm25_map, targets)

            image_candidates = [
                ("image_blended", row["image_blended_rank"], row["image_blended_match"]),
                ("image_dino", row["image_dino_rank"], row["image_dino_match"]),
                ("image_metaclip", row["image_metaclip_rank"], row["image_metaclip_match"]),
            ]
            text_candidates = [
                ("text_metaclip", row["text_metaclip_rank"], row["text_metaclip_match"]),
                ("text_ranked", row["text_ranked_rank"], row["text_ranked_match"]),
                ("bm25", row["bm25_rank"], row["bm25_match"]),
            ]

            (
                row["image_union_rank"],
                row["image_union_match"],
                row["image_union_source"],
            ) = best_union_candidate(image_candidates)
            (
                row["text_union_rank"],
                row["text_union_match"],
                row["text_union_source"],
            ) = best_union_candidate(text_candidates)

            (
                row["overall_union_rank"],
                row["overall_union_match"],
                row["overall_union_source"],
            ) = best_union_candidate(image_candidates + text_candidates)

            dump_debug_record(
                dump_dir,
                idx=idx,
                x_entry=x,
                targets=targets,
                request_text=text,
                response=response,
                debug=debug,
                row_snapshot=row.copy(),
            )

            writer.writerow(row)
            records.append(row)

    metric_names = [
        "image_blended_rank",
        "image_dino_rank",
        "image_metaclip_rank",
        "text_metaclip_rank",
        "text_ranked_rank",
        "bm25_rank",
        "image_union_rank",
        "text_union_rank",
        "overall_union_rank",
    ]

    summary = compute_metrics(records, metric_names, args.ks)

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\nEvaluation complete.")
    print("Results saved to:", results_path)
    print("Summary saved to:", summary_path)
    print("\nRecall / MRR summary:")
    for metric, stats in summary.items():
        stats_line = ", ".join(f"{key}={value:.3f}" for key, value in stats.items())
        print(f"  {metric}: {stats_line}")


if __name__ == "__main__":
    main()
