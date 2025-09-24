"""In-memory trademark catalogue used for tests and demos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from app.services.embedding_utils import hashed_embedding, tokenize


@dataclass(frozen=True)
class TrademarkRecord:
    trademark_id: str
    title: str
    status: str
    class_codes: List[str]
    app_no: str
    goods_services: str
    decision_text: str
    thumb_url: str
    image_tokens: List[str]
    text_tokens: List[str]

    @property
    def image_embedding(self) -> List[float]:
        return hashed_embedding(self.image_tokens)

    @property
    def text_embedding(self) -> List[float]:
        return hashed_embedding(self.text_tokens)


_CATALOG: List[TrademarkRecord] = [
    TrademarkRecord(
        trademark_id="T001",
        title="STARBUCKS",
        status="registered",
        class_codes=["30"],
        app_no="10-2000-0001",
        goods_services="커피, 차, 코코아 및 이와 관련된 음료",
        decision_text="상표가 커피 전문점과 연관되어 등록 승인됨",
        thumb_url="https://assets.example/starbucks.png",
        image_tokens=["green", "mermaid", "coffee", "circle", "starbucks"],
        text_tokens=tokenize("Starbucks coffee shop beverages mermaid logo"),
    ),
    TrademarkRecord(
        trademark_id="T002",
        title="STARBRIGHT",
        status="refused",
        class_codes=["30"],
        app_no="10-2015-0030",
        goods_services="커피, 과자, 빵",
        decision_text="기존 등록상표와 유사하여 거절됨",
        thumb_url="https://assets.example/starbright.png",
        image_tokens=["yellow", "star", "text", "starbright"],
        text_tokens=tokenize("Starbright coffee snack brand stylised star"),
    ),
    TrademarkRecord(
        trademark_id="T003",
        title="SUNNY MOON",
        status="registered",
        class_codes=["43"],
        app_no="40-2018-1001",
        goods_services="카페, 레스토랑 서비스",
        decision_text="레스토랑 프랜차이즈로 등록",
        thumb_url="https://assets.example/sunnymoon.png",
        image_tokens=["sun", "moon", "cafe", "yellow", "blue"],
        text_tokens=tokenize("Restaurant services cafe brunch sunny moon"),
    ),
    TrademarkRecord(
        trademark_id="T004",
        title="MOONLIGHT CAFE",
        status="pending",
        class_codes=["43"],
        app_no="40-2020-0043",
        goods_services="커피숍, 디저트 카페",
        decision_text="심사 진행 중",
        thumb_url="https://assets.example/moonlight.png",
        image_tokens=["moon", "coffee", "cup", "night"],
        text_tokens=tokenize("Moonlight cafe dessert coffee night"),
    ),
]


def all_trademarks() -> List[TrademarkRecord]:
    return list(_CATALOG)


def by_id(trademark_id: str) -> TrademarkRecord:
    for record in _CATALOG:
        if record.trademark_id == trademark_id:
            return record
    raise KeyError(trademark_id)


def bulk_by_ids(ids: Iterable[str]) -> Dict[str, TrademarkRecord]:
    id_set = set(ids)
    return {rec.trademark_id: rec for rec in _CATALOG if rec.trademark_id in id_set}
