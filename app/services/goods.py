"""Helpers for loading goods/service class adjacency information."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple

BASE_DIR = Path(__file__).resolve().parents[1]
TSV_PATH = BASE_DIR / "data" / "goods_services" / "ko_goods_services.tsv"

GoodsMeta = Dict[str, Dict[str, Set[str]]]
GroupIndex = Dict[str, Set[str]]


@lru_cache(maxsize=1)
def load_goods_groups() -> Tuple[GoodsMeta, GroupIndex]:
    meta: GoodsMeta = {}
    groups: GroupIndex = {}
    with TSV_PATH.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            nc = row["nc_class"].strip()
            raw_groups = row["similar_group_code"].strip()
            group_codes = {code.strip() for code in raw_groups.split(",") if code.strip()}
            if not group_codes:
                continue
            meta[nc] = {"groups": group_codes}
            for code in group_codes:
                groups.setdefault(code, set()).add(nc)
    return meta, groups


def is_adjacent(user_classes: Iterable[str], target_classes: Iterable[str], meta: GoodsMeta) -> bool:
    user_groups = set()
    for cls in user_classes:
        entry = meta.get(cls)
        if entry:
            user_groups.update(entry["groups"])
    if not user_groups:
        return False

    for cls in target_classes:
        entry = meta.get(cls)
        if not entry:
            continue
        if user_groups & entry["groups"]:
            return True
    return False
