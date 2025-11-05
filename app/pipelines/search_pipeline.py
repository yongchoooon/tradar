"""Multimodal search pipeline built on pgvector + OpenSearch."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from app.schemas.search import (
    QueryInfo,
    SearchRequest,
    SearchResponse,
    SearchResult,
    DebugInfo,
    DebugRow,
    ImageBlendDebugRow,
)
from app.services.bm25_client import BM25Client
from app.services.catalog import TrademarkRecord, bulk_by_ids
from app.services.embedding_utils import normalize_accumulator
# goods metadata currently not used for grouping; import retained for future use
# from app.services.goods import load_goods_groups
from app.services.image_embed_service import ImageEmbedder
from app.services.text_embed_service import TextEmbedder
from app.services.text_variant_service import TextVariantService
from app.services.vector_client import VectorClient


IMAGE_TOPN = 100
TEXT_TOPN = 100
DEFAULT_TOPK = 20
MISC_LIMIT = 10
DEBUG_LIMIT: Optional[int] = None  # None means show all debug rows

IMAGE_WEIGHT_DINO = 0.5
IMAGE_WEIGHT_METACLIP = 0.5

PRIMARY_STATUSES = {
    "등록",
    "공고",
    "registered",
    "publication",
    "public",
    "notified",
}


@dataclass
class ImageCandidate:
    dino: float = 0.0
    metaclip: float = 0.0

    @property
    def blended(self) -> float:
        return _blend_scores(
            [
                (self.dino, IMAGE_WEIGHT_DINO),
                (self.metaclip, IMAGE_WEIGHT_METACLIP),
            ]
        )


@dataclass
class TextCandidate:
    metaclip: float = 0.0
    bm25: float = 0.0


class SearchPipeline:
    """Coordinate ANN/BM25 retrieval and scoring."""

    def __init__(self) -> None:
        self._vector = VectorClient()
        self._img_embed = ImageEmbedder()
        self._txt_embed = TextEmbedder()
        self._variants = TextVariantService()
        try:
            self._bm25: BM25Client | None = BM25Client()
        except RuntimeError:
            self._bm25 = None

    def search(self, req: SearchRequest) -> SearchResponse:
        topk = req.k if req.k > 0 else DEFAULT_TOPK

        image_bytes = base64.b64decode(req.image_b64)
        image_embeddings = self._img_embed.encode(image_bytes)
        dino_query = image_embeddings["dino"]
        metaclip_query = image_embeddings["metaclip"]

        dino_hits = self._vector.search_image("dino", dino_query, IMAGE_TOPN)
        metaclip_hits = self._vector.search_image("metaclip", metaclip_query, IMAGE_TOPN)
        image_candidates = self._score_image_candidates(
            dino_hits, metaclip_hits, dino_query, metaclip_query
        )

        manual_text = (req.text or "").strip()
        variants = self._collect_variants(manual_text)
        text_query = self._build_text_query_vector(manual_text, variants)
        text_hits: List[dict] = []
        if text_query is not None:
            text_hits = self._vector.search_text(text_query, TEXT_TOPN)
        bm25_hits = self._search_bm25(manual_text, variants)
        text_candidates = self._score_text_candidates(text_hits, bm25_hits, text_query)

        image_sorted_ids = _sorted_ids(
            {tm_id: cand.blended for tm_id, cand in image_candidates.items()}
        )
        text_sorted_ids = _sorted_ids(
            {tm_id: cand.metaclip for tm_id, cand in text_candidates.items()}
        )

        image_top_ids = image_sorted_ids[:topk]
        text_top_ids = text_sorted_ids[:topk]
        image_misc_candidate_ids = image_sorted_ids[topk : topk + MISC_LIMIT]
        text_misc_candidate_ids = text_sorted_ids[topk : topk + MISC_LIMIT]

        required_ids = set(
            image_top_ids
            + text_top_ids
            + image_misc_candidate_ids
            + text_misc_candidate_ids
        )
        metadata = bulk_by_ids(required_ids)

        image_top = self._build_results(
            image_top_ids, metadata, image_candidates, text_candidates
        )
        text_top = self._build_results(
            text_top_ids, metadata, image_candidates, text_candidates
        )

        image_misc = self._build_misc_results(
            image_misc_candidate_ids, metadata, image_candidates, text_candidates
        )
        text_misc = self._build_misc_results(
            text_misc_candidate_ids, metadata, image_candidates, text_candidates
        )

        debug_info: DebugInfo | None = None
        if req.debug:
            debug_info = self._build_debug_info(
                image_candidates=image_candidates,
                text_candidates=text_candidates,
                bm25_hits=bm25_hits,
                image_sorted_ids=image_sorted_ids,
                text_sorted_ids=text_sorted_ids,
            )

        query_info = QueryInfo(
            k=topk,
            text=manual_text,
            goods_classes=req.goods_classes,
            group_codes=req.group_codes,
            variants=variants,
        )
        return SearchResponse(
            query=query_info,
            image_top=image_top,
            image_misc=image_misc,
            text_top=text_top,
            text_misc=text_misc,
            debug=debug_info,
        )

    def _collect_variants(self, text: str) -> List[str]:
        text = (text or "").strip()
        if not text:
            return []
        variants = self._variants.generate(text)
        seen = {text.lower()}
        unique: List[str] = []
        for cand in variants:
            key = cand.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(cand)
        return unique

    def _build_text_query_vector(
        self, text: str, variants: Sequence[str]
    ) -> List[float] | None:
        terms: List[str] = []
        if text.strip():
            terms.append(text)
        for variant in variants:
            if variant.strip():
                terms.append(variant)
        if not terms:
            return None

        vectors = []
        weights = []
        for idx, term in enumerate(terms):
            vectors.append(self._txt_embed.encode(term))
            weights.append(1.0 if idx == 0 else 0.8)

        dim = len(vectors[0])
        accum = [0.0] * dim
        for vec, weight in zip(vectors, weights):
            if len(vec) != dim:
                raise ValueError("Mismatched text embedding dimensions")
            for i, value in enumerate(vec):
                accum[i] += value * weight
        return normalize_accumulator(accum)

    def _search_bm25(self, text: str, variants: Sequence[str]) -> List[dict]:
        if not self._bm25:
            return []
        terms = [text.strip()] + [variant.strip() for variant in variants]
        query = " ".join(term for term in terms if term)
        if not query:
            return []
        return self._bm25.search(query, topn=TEXT_TOPN)

    def _score_image_candidates(
        self,
        dino_hits: List[dict],
        metaclip_hits: List[dict],
        dino_query: Sequence[float],
        metaclip_query: Sequence[float],
    ) -> Dict[str, ImageCandidate]:
        candidates: Dict[str, ImageCandidate] = {}
        for hit in dino_hits:
            tm_id = hit.get("id")
            if not tm_id:
                continue
            candidates.setdefault(tm_id, ImageCandidate())

        for hit in metaclip_hits:
            tm_id = hit.get("id")
            if not tm_id:
                continue
            candidates.setdefault(tm_id, ImageCandidate())

        candidate_ids = list(candidates.keys())
        if not candidate_ids:
            return candidates

        dino_vectors = self._vector.get_image_embeddings("dino", candidate_ids)
        dino_scores = self._vector.cosine_scores(dino_query, dino_vectors)
        for tm_id in candidate_ids:
            cand = candidates.setdefault(tm_id, ImageCandidate())
            cand.dino = dino_scores.get(tm_id, -1.0)

        metaclip_vectors = self._vector.get_image_embeddings("metaclip", candidate_ids)
        metaclip_scores = self._vector.cosine_scores(metaclip_query, metaclip_vectors)
        for tm_id in candidate_ids:
            cand = candidates.setdefault(tm_id, ImageCandidate())
            cand.metaclip = metaclip_scores.get(tm_id, -1.0)

        return candidates

    def _score_text_candidates(
        self,
        vector_hits: List[dict],
        bm25_hits: List[dict],
        query_vector: Sequence[float] | None,
    ) -> Dict[str, TextCandidate]:
        candidates: Dict[str, TextCandidate] = {}
        for hit in vector_hits:
            tm_id = hit.get("id")
            if not tm_id:
                continue
            candidates.setdefault(tm_id, TextCandidate())

        for hit in bm25_hits:
            tm_id = hit.get("id")
            if not tm_id:
                continue
            cand = candidates.setdefault(tm_id, TextCandidate())
            cand.bm25 = max(cand.bm25, float(hit.get("score") or 0.0))

        if not candidates:
            return candidates

        if query_vector is not None:
            ids = list(candidates.keys())
            embeddings = self._vector.get_text_embeddings(ids)
            scores = self._vector.cosine_scores(query_vector, embeddings)
            for tm_id in ids:
                cand = candidates.setdefault(tm_id, TextCandidate())
                cand.metaclip = scores.get(tm_id, -1.0)

        return candidates

    def _build_results(
        self,
        ids: List[str],
        metadata: Dict[str, TrademarkRecord],
        image_candidates: Dict[str, ImageCandidate],
        text_candidates: Dict[str, TextCandidate],
    ) -> List[SearchResult]:
        results: List[SearchResult] = []
        for app_no in ids:
            record = metadata.get(app_no)
            if not record:
                continue
            image_cand = image_candidates.get(app_no, ImageCandidate())
            text_cand = text_candidates.get(app_no, TextCandidate())
            title = _display_title(record)
            status = (record.status or '').strip() or '상태 미상'
            results.append(
                SearchResult(
                    trademark_id=record.application_number,
                    title=title,
                    status=status,
                    class_codes=record.class_codes,
                    app_no=record.application_number,
                    image_sim=round(image_cand.blended, 4),
                    text_sim=round(text_cand.metaclip, 4),
                    thumb_url=record.thumb_url,
                    doi=record.doi,
                )
            )
        return results

    def _build_misc_results(
        self,
        ids: List[str],
        metadata: Dict[str, TrademarkRecord],
        image_candidates: Dict[str, ImageCandidate],
        text_candidates: Dict[str, TextCandidate],
    ) -> List[SearchResult]:
        misc: List[SearchResult] = []
        for result in self._build_results(ids, metadata, image_candidates, text_candidates):
            if _is_primary_status(result.status):
                continue
            misc.append(result)
        return misc
        
    def _build_debug_info(
        self,
        image_candidates: Dict[str, ImageCandidate],
        text_candidates: Dict[str, TextCandidate],
        bm25_hits: Sequence[dict],
        image_sorted_ids: Sequence[str],
        text_sorted_ids: Sequence[str],
    ) -> DebugInfo:
        limit = DEBUG_LIMIT
        image_dino_rows = _build_metric_debug_rows(
            image_candidates, "dino", limit
        )
        image_metaclip_rows = _build_metric_debug_rows(
            image_candidates, "metaclip", limit
        )
        text_metaclip_rows = _build_metric_debug_rows(
            text_candidates, "metaclip", limit
        )
        text_bm25_rows = _rows_from_hits(bm25_hits, limit)

        image_blended_rows = _build_image_blend_rows(
            image_sorted_ids, image_candidates, limit
        )
        text_ranked_rows = _build_rows_from_ids(
            text_sorted_ids, text_candidates, "metaclip", limit, rescale=False
        )

        return DebugInfo(
            image_dino=image_dino_rows,
            image_metaclip=image_metaclip_rows,
            text_metaclip=text_metaclip_rows,
            text_bm25=text_bm25_rows,
            image_blended=image_blended_rows,
            text_ranked=text_ranked_rows,
        )


def _blend_scores(pairs: Iterable[tuple[float, float]]) -> float:
    valid = [(score, weight) for score, weight in pairs if weight > 0.0]
    if not valid:
        return 0.0
    weight_sum = sum(weight for _, weight in valid)
    if weight_sum == 0.0:
        return 0.0
    return sum(score * weight for score, weight in valid) / weight_sum


def _sorted_ids(scores: Dict[str, float]) -> List[str]:
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [tm_id for tm_id, score in ordered if score >= 0.0]


def _is_primary_status(status: str) -> bool:
    normalized = (status or "").strip().lower()
    return normalized in {name.lower() for name in PRIMARY_STATUSES}


def _display_title(record: TrademarkRecord | None) -> str:
    if not record:
        return '(상표명 없음)'
    title_ko = (record.title_korean or '').strip()
    if title_ko and title_ko == record.application_number:
        title_ko = ''
    title_en = (record.title_english or '').strip()
    if title_en and title_en == record.application_number:
        title_en = ''
    return title_ko or title_en or '(상표명 없음)'


def _candidate_metric(candidate, metric: str) -> float:
    if metric == "blended":
        return float(candidate.blended)
    return float(getattr(candidate, metric, 0.0) or 0.0)


def _build_rows_from_ids(
    ids: Sequence[str],
    candidates: Dict[str, object],
    metric: str,
    limit: Optional[int],
    *,
    rescale: bool,
) -> List[DebugRow]:
    items: List[tuple[str, float]] = []
    sliced_ids = ids if limit is None or limit < 0 else ids[:limit]
    for tm_id in sliced_ids:
        cand = candidates.get(tm_id)
        if not cand:
            continue
        score = _candidate_metric(cand, metric)
        items.append((tm_id, score))
    items.sort(key=lambda pair: pair[1], reverse=True)
    return _rows_from_items(items, rescale=rescale)


def _rows_from_hits(
    hits: Sequence[dict], limit: Optional[int], *, rescale: bool = False
) -> List[DebugRow]:
    rows: List[DebugRow] = []
    rank = 1
    for hit in hits:
        if limit is not None and limit >= 0 and rank > limit:
            break
        tm_id = hit.get("id")
        if not tm_id:
            continue
        score = float(hit.get("score") or 0.0)
        rows.append(
            DebugRow(
                rank=rank,
                application_number=tm_id,
                score=round(score, 4),
            )
        )
        rank += 1
    return rows


def _rows_from_items(
    items: Sequence[tuple[str, float]], *, rescale: bool = False
) -> List[DebugRow]:
    rows: List[DebugRow] = []
    for rank, (tm_id, score) in enumerate(items, start=1):
        value = score
        rows.append(
            DebugRow(
                rank=rank,
                application_number=tm_id,
                score=round(float(value), 4),
            )
        )
    return rows


def _build_metric_debug_rows(
    candidates: Dict[str, object], metric: str, limit: Optional[int]
) -> List[DebugRow]:
    items: List[tuple[str, float]] = []
    for tm_id, candidate in candidates.items():
        score = _candidate_metric(candidate, metric)
        items.append((tm_id, score))
    items.sort(key=lambda pair: pair[1], reverse=True)
    if limit is not None and limit >= 0:
        items = items[:limit]
    return [
        DebugRow(rank=idx + 1, application_number=tm_id, score=round(score, 4))
        for idx, (tm_id, score) in enumerate(items)
    ]


def _build_image_blend_rows(
    ids: Sequence[str],
    candidates: Dict[str, ImageCandidate],
    limit: Optional[int],
) -> List[ImageBlendDebugRow]:
    rows: List[ImageBlendDebugRow] = []
    sliced_ids = ids if limit is None or limit < 0 else ids[:limit]
    for rank, tm_id in enumerate(sliced_ids, start=1):
        cand = candidates.get(tm_id)
        if not cand:
            continue
        dino = cand.dino
        metaclip = cand.metaclip
        rows.append(
            ImageBlendDebugRow(
                rank=rank,
                application_number=tm_id,
                dino=round(dino, 4),
                metaclip=round(metaclip, 4),
                blended=round(cand.blended, 4),
            )
        )
    return rows
