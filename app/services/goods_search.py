"""상품/서비스류 키워드 검색 서비스."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Set, Tuple

from app.schemas.goods import GoodsClassItem, GoodsGroupItem, GoodsSearchResponse
from app.services.embedding_utils import (
    DEFAULT_DIM,
    cosine,
    hashed_embedding,
    normalize_accumulator,
    token_hash_index,
    tokenize,
)

BASE_DIR = Path(__file__).resolve().parents[1]
GOODS_TSV = BASE_DIR / "data" / "goods_services" / "ko_goods_services.tsv"
CLASSES_TSV = BASE_DIR / "data" / "goods_services" / "nice_classes_ko_compact.tsv"


def _zero_accumulator() -> List[float]:
    return [0.0] * DEFAULT_DIM


@dataclass
class GroupEntry:
    code: str
    names: List[str] = field(default_factory=list)
    name_tokens: Dict[str, Set[str]] = field(default_factory=dict)
    name_lower: Dict[str, str] = field(default_factory=dict, repr=False)
    vector: List[float] = field(default_factory=list)
    _name_set: Set[str] = field(default_factory=set, repr=False)
    token_set: Set[str] = field(default_factory=set, repr=False)
    _accum: List[float] = field(default_factory=_zero_accumulator, repr=False)

    def add_name(self, name: str) -> None:
        if name in self._name_set:
            return
        tokens = tokenize(name)
        token_set = set(tokens)
        self.names.append(name)
        self.name_tokens[name] = token_set
        self.name_lower[name] = name.lower()
        self._name_set.add(name)
        for tok in token_set:
            if not tok:
                continue
            self.token_set.add(tok)
            self._accum[token_hash_index(tok)] += 1.0

    def finalize(self) -> None:
        self.vector = normalize_accumulator(self._accum)


@dataclass
class ClassEntry:
    nc_class: str
    name: str
    tokens: List[str]
    token_set: set[str]
    vector: List[float]
    groups: Dict[str, GroupEntry]


def _load_class_descriptions() -> Dict[str, Tuple[str, List[str], set[str], List[float]]]:
    mapping: Dict[str, Tuple[str, List[str], set[str], List[float]]] = {}
    with CLASSES_TSV.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            nc = row["nc_class"].strip()
            name = row["content"].strip()
            tokens = tokenize(name)
            token_set = set(tokens)
            mapping[nc] = (name, tokens, token_set, hashed_embedding(tokens or ["blank"]))
    return mapping


def _load_goods_entries() -> Dict[str, ClassEntry]:
    classes = _load_class_descriptions()
    class_map: Dict[str, ClassEntry] = {}
    with GOODS_TSV.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            nc = row["nc_class"].strip()
            name = row["name_ko"].strip()
            group_code = row["similar_group_code"].strip()
            if not nc or not group_code:
                continue
            if nc not in class_map:
                class_name, tokens, token_set, vector = classes.get(
                    nc,
                    (f"{nc}류", [nc], {nc}, hashed_embedding([nc])),
                )
                class_map[nc] = ClassEntry(
                    nc_class=nc,
                    name=class_name,
                    tokens=tokens,
                    token_set=token_set,
                    vector=vector,
                    groups={},
                )
            entry = class_map[nc].groups.setdefault(group_code, GroupEntry(code=group_code))
            entry.add_name(name)
    for entry in class_map.values():
        for group in entry.groups.values():
            group.finalize()
    return class_map


@lru_cache(maxsize=1)
def _catalog() -> Dict[str, ClassEntry]:
    return _load_goods_entries()


def _similarity(query_vec: List[float], candidate_vec: List[float]) -> float:
    if not query_vec or not candidate_vec:
        return 0.0
    return float(cosine(query_vec, candidate_vec))


def _match_name(tokens: Set[str], text: str, query_terms: List[str]) -> tuple[bool, Set[str]]:
    scoring_tokens = set(tokens)
    for term in query_terms:
        if term in scoring_tokens:
            continue
        if term and term in text:
            scoring_tokens.add(term)
            continue
        return False, set()
    return True, scoring_tokens


def search_goods(query: str, limit: int = 10) -> GoodsSearchResponse:
    query = (query or "").strip()
    if not query:
        return GoodsSearchResponse(query="", results=[])

    catalog = _catalog()
    query_terms = tokenize(query)
    if not query_terms:
        query_terms = [query.lower()]
    query_set = set(query_terms)
    query_vec = hashed_embedding(query_terms or [query.lower()])

    scored_classes: List[Tuple[float, ClassEntry, List[GoodsGroupItem]]] = []
    for entry in catalog.values():
        class_tokens_accum: List[str] = list(entry.tokens)
        class_token_set: Set[str] = set(entry.token_set)
        class_name_lower = entry.name.lower()
        for term in query_terms:
            if term and term in class_name_lower:
                class_token_set.add(term)
                class_tokens_accum.append(term)

        group_items: List[GoodsGroupItem] = []
        for group in entry.groups.values():
            filtered_names: List[str] = []
            group_token_accum: List[str] = []
            group_token_set: Set[str] = set()
            for name in group.names:
                tokens = group.name_tokens.get(name, set())
                text = group.name_lower.get(name, name.lower())
                matched, scoring_tokens = _match_name(tokens, text, query_terms)
                if not matched:
                    continue
                filtered_names.append(name)
                group_token_accum.extend(scoring_tokens)
                group_token_set.update(scoring_tokens)
            if not filtered_names:
                continue

            vec_tokens = group_token_accum or [group.code.lower()]
            group_vec = hashed_embedding(vec_tokens)
            overlap = len(query_set & group_token_set) / len(query_set) if query_set else 0.0
            vec_score = _similarity(query_vec, group_vec)
            group_score = overlap * 0.7 + vec_score * 0.3
            group_items.append(
                GoodsGroupItem(
                    similar_group_code=group.code,
                    names=filtered_names[:20],
                    score=round(group_score, 4),
                )
            )

        if not group_items:
            continue

        group_items.sort(key=lambda g: g.score, reverse=True)

        class_vec_tokens = class_tokens_accum or [entry.nc_class]
        class_vec = hashed_embedding(class_vec_tokens)
        class_overlap = len(query_set & class_token_set) / len(query_set) if query_set else 0.0
        class_vec_score = _similarity(query_vec, class_vec)
        class_score = class_overlap * 0.6 + class_vec_score * 0.4
        if any(term and term in class_name_lower for term in query_terms):
            class_score += 0.1
        best_group_score = group_items[0].score if group_items else 0.0
        combined = class_score * 0.3 + best_group_score * 0.7

        scored_classes.append((combined, entry, group_items))

    scored_classes.sort(key=lambda item: item[0], reverse=True)
    top = scored_classes[:limit]

    results = [
        GoodsClassItem(
            nc_class=entry.nc_class,
            class_name=entry.name,
            score=round(score, 4),
            groups=group_items,
        )
        for score, entry, group_items in top
    ]
    return GoodsSearchResponse(query=query, results=results)
