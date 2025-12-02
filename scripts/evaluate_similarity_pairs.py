#!/usr/bin/env python
"""Evaluate search recall using published similar trademark pairs."""

from __future__ import annotations

import argparse
import base64
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

try:  # pragma: no cover - optional dependency guard
    from tqdm import tqdm  # type: ignore
except Exception:  # pragma: no cover
    def tqdm(iterable, **kwargs):  # type: ignore
        return iterable

from app.pipelines.search_pipeline import SearchPipeline
from app.schemas.search import DebugInfo, DebugRow, ImageBlendDebugRow, SearchRequest


def load_pairs(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON must contain a list of entries")
    return data


def choose_text(entry: dict) -> Optional[str]:
    title_ko = (entry.get("title_korean") or "").strip()
    title_en = (entry.get("title_english") or "").strip()
    if title_ko:
        return title_ko
    if title_en:
        return title_en
    return " "  # return a single space to avoid empty-text pipeline errors


def find_rank(debug_rows: Iterable[DebugRow], target: str) -> Optional[int]:
    for row in debug_rows:
        if row.application_number == target:
            return row.rank
    return None


def find_blend_rank(rows: Iterable[ImageBlendDebugRow], target: str) -> Optional[int]:
    for row in rows:
        if row.application_number == target:
            return row.rank
    return None


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate trademark search recall using labelled similar pairs.")
    parser.add_argument(
        "--pairs-json",
        type=Path,
        default=Path("published_similar_pair_data_i_have.json"),
        help="Path to the JSON file containing x/y pair records.",
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
        default=50,
        help="Top-K size to request from the pipeline (default: 50).",
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

    args = parser.parse_args()

    pairs = load_pairs(args.pairs_json)
    ensure_dir(args.output_dir)

    pipeline = SearchPipeline()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    exp_prefix = args.experiment_name.strip().replace(" ", "_")
    if exp_prefix:
        exp_prefix = f"{exp_prefix}_"
    results_path = args.output_dir / f"{exp_prefix}similar_pairs_eval_{timestamp}.csv"
    summary_path = args.output_dir / f"{exp_prefix}similar_pairs_eval_{timestamp}_summary.json"

    fieldnames = [
        "index",
        "x_application_number",
        "y_application_number",
        "image_blended_rank",
        "image_dino_rank",
        "image_metaclip_rank",
        "text_metaclip_rank",
        "text_ranked_rank",
        "bm25_rank",
        "image_union_rank",
        "text_union_rank",
        "overall_union_rank",
        "error",
    ]

    records: List[dict] = []

    with results_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for idx, pair in enumerate(tqdm(pairs, desc="Evaluating"), start=1):
            x = pair.get("x", {})
            y = pair.get("y", {})
            y_app = y.get("application_number")

            row = {
                "index": idx,
                "x_application_number": x.get("application_number"),
                "y_application_number": y_app,
                "image_blended_rank": None,
                "image_dino_rank": None,
                "image_metaclip_rank": None,
                "text_metaclip_rank": None,
                "text_ranked_rank": None,
                "bm25_rank": None,
                "image_union_rank": None,
                "text_union_rank": None,
                "overall_union_rank": None,
                "error": None,
            }

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

            row["image_blended_rank"] = find_blend_rank(debug.image_blended, y_app)
            row["image_dino_rank"] = find_rank(debug.image_dino, y_app)
            row["image_metaclip_rank"] = find_rank(debug.image_metaclip, y_app)
            row["text_metaclip_rank"] = find_rank(debug.text_metaclip, y_app)
            row["text_ranked_rank"] = find_rank(debug.text_ranked, y_app)
            row["bm25_rank"] = find_rank(debug.text_bm25, y_app)

            image_ranks = [
                r
                for r in [row["image_blended_rank"], row["image_dino_rank"], row["image_metaclip_rank"]]
                if isinstance(r, int) and r > 0
            ]
            text_ranks = [
                r
                for r in [row["text_metaclip_rank"], row["text_ranked_rank"], row["bm25_rank"]]
                if isinstance(r, int) and r > 0
            ]
            all_ranks = image_ranks + text_ranks

            row["image_union_rank"] = min(image_ranks) if image_ranks else None
            row["text_union_rank"] = min(text_ranks) if text_ranks else None
            row["overall_union_rank"] = min(all_ranks) if all_ranks else None

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
