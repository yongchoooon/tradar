"""Multimodal search pipeline following the v2 design."""

from __future__ import annotations

import base64
import io
from collections import defaultdict
from typing import Iterable, List

from app.schemas.search import (
    BoundingBox,
    QueryInfo,
    SearchGroups,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.services.bm25_client import BM25Client
from app.services.catalog import bulk_by_ids
from app.services.goods import is_adjacent, load_goods_groups
from app.services.image_embed_service import ImageEmbedder
from app.services.ocr_service import OCRService
from app.services.text_embed_service import TextEmbedder
from app.services.vector_client import VectorClient

_DEFAULT_TOPN = 50


class SearchPipeline:
    def __init__(self) -> None:
        self._vector = VectorClient()
        self._bm25 = BM25Client()
        self._img_embed = ImageEmbedder()
        self._txt_embed = TextEmbedder()
        self._ocr = OCRService()

    def search(self, req: SearchRequest) -> SearchResponse:
        image_bytes = base64.b64decode(req.image_b64)
        query_images = make_query_images(image_bytes, req.boxes)

        image_vectors = [self._img_embed.encode(img) for img in query_images]
        ocr_texts = [self._ocr.extract(img) for img in query_images]
        manual_text = (req.text or "").strip()
        text_pieces = []
        if manual_text:
            text_pieces.append(manual_text)
        text_pieces.extend(text for text in ocr_texts if text)
        joined_text = " ".join(text_pieces)
        text_vector = self._txt_embed.encode(joined_text or manual_text)

        bm25_query = joined_text or ""

        img_hits_list = [
            self._vector.search("image", vec, topn=_DEFAULT_TOPN)
            for vec in image_vectors
        ]
        txt_hits = self._vector.search("text", text_vector, topn=_DEFAULT_TOPN)
        bm25_hits = self._bm25.search(bm25_query, topn=_DEFAULT_TOPN)

        candidates = merge_hits(img_hits_list, txt_hits, bm25_hits)

        topk_img_ids = topk_by(candidates, "image_sim", req.k)
        topk_txt_ids = topk_by(candidates, "text_sim", req.k)

        meta = bulk_by_ids(set(topk_img_ids + topk_txt_ids))
        goods_meta, _ = load_goods_groups()
        user_classes = set(req.goods_classes)

        img_results = build_results(topk_img_ids, candidates, meta)
        txt_results = build_results(topk_txt_ids, candidates, meta)

        img_groups = group_results(img_results, user_classes, goods_meta)
        txt_groups = group_results(txt_results, user_classes, goods_meta)

        query_info = QueryInfo(
            k=req.k,
            boxes=len(req.boxes),
            text=req.text,
            goods_classes=req.goods_classes,
            group_codes=req.group_codes,
        )
        return SearchResponse(
            query=query_info,
            image_topk=img_groups,
            text_topk=txt_groups,
        )


def make_query_images(image_bytes: bytes, boxes: List[BoundingBox]) -> List[bytes]:
    crops: List[bytes] = []
    if not boxes:
        return [image_bytes]

    try:
        from PIL import Image
    except Exception:  # pillow not available; fall back to duplicates
        return [image_bytes] + [image_bytes for _ in boxes[:2]]

    with Image.open(io.BytesIO(image_bytes)) as img:
        img = img.convert("RGB")
        width, height = img.size
        for box in boxes[:2]:  # 최대 2개 크롭 → 원본 포함 3개
            x1, y1, x2, y2 = _denorm_box(box, width, height)
            cropped = img.crop((x1, y1, x2, y2))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            crops.append(buf.getvalue())
    return [image_bytes] + crops


def _denorm_box(box: BoundingBox, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = int(max(0.0, min(1.0, box.x1)) * width)
    y1 = int(max(0.0, min(1.0, box.y1)) * height)
    x2 = int(max(0.0, min(1.0, box.x2)) * width)
    y2 = int(max(0.0, min(1.0, box.y2)) * height)
    if x1 == x2:
        x2 = min(width, x1 + 1)
    if y1 == y2:
        y2 = min(height, y1 + 1)
    return x1, y1, x2, y2


def merge_hits(
    img_hits_list: List[List[dict]],
    txt_hits: List[dict],
    bm25_hits: List[dict],
) -> dict:
    candidates = defaultdict(
        lambda: {
            "image_sim": 0.0,
            "text_sim_vec": 0.0,
            "text_sim_bm25": 0.0,
            "text_sim": 0.0,
        }
    )

    for hits in img_hits_list:
        for hit in hits:
            tm_id = hit["id"]
            candidates[tm_id]["image_sim"] = max(
                candidates[tm_id]["image_sim"], hit["score"]
            )

    for hit in txt_hits:
        tm_id = hit["id"]
        candidates[tm_id]["text_sim_vec"] = max(
            candidates[tm_id]["text_sim_vec"], hit["score"]
        )

    if bm25_hits:
        scores = [hit["score"] for hit in bm25_hits]
        min_s, max_s = min(scores), max(scores)
    else:
        min_s = max_s = 0.0

    for hit in bm25_hits:
        tm_id = hit["id"]
        norm_score = bm25_norm(hit["score"], min_s, max_s)
        candidates[tm_id]["text_sim_bm25"] = max(
            candidates[tm_id]["text_sim_bm25"], norm_score
        )

    for payload in candidates.values():
        payload["text_sim"] = max(
            payload["text_sim_vec"], payload["text_sim_bm25"]
        )
    return candidates


def bm25_norm(score: float, min_s: float, max_s: float) -> float:
    if max_s == min_s:
        return 0.0 if score == 0 else 1.0
    return (score - min_s) / (max_s - min_s)


def topk_by(candidates: dict, key: str, k: int) -> List[str]:
    ordered = sorted(
        candidates.items(), key=lambda item: item[1][key], reverse=True
    )
    filtered = [tm_id for tm_id, payload in ordered if payload[key] > 0]
    return filtered[:k]


def build_results(
    ids: List[str],
    scores: dict,
    meta: dict,
) -> List[SearchResult]:
    results = []
    for tm_id in ids:
        record = meta.get(tm_id)
        if not record:
            continue
        payload = scores[tm_id]
        results.append(
            SearchResult(
                trademark_id=tm_id,
                title=record.title,
                status=record.status,
                class_codes=record.class_codes,
                app_no=record.app_no,
                image_sim=round(payload["image_sim"], 4),
                text_sim=round(payload["text_sim"], 4),
                thumb_url=record.thumb_url,
            )
        )
    return results


def group_results(
    results: List[SearchResult],
    user_classes: Iterable[str],
    goods_meta: dict,
) -> SearchGroups:
    user_set = set(user_classes)
    groups = SearchGroups()
    for res in results:
        target_set = set(res.class_codes)
        if is_adjacent(user_set, target_set, goods_meta):
            groups.adjacent.append(res)
        else:
            groups.non_adjacent.append(res)

        if res.status == "registered":
            groups.registered.append(res)
        elif res.status == "refused":
            groups.refused.append(res)
        else:
            groups.others.append(res)
    return groups
