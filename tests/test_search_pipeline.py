import base64

from app.pipelines.search_pipeline import SearchPipeline
from app.schemas.search import BoundingBox, SearchRequest


def encode_image(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_multimodal_pipeline_groups_results():
    pipeline = SearchPipeline()
    req = SearchRequest(
        image_b64=encode_image("Starbucks coffee mermaid logo"),
        boxes=[BoundingBox(0.0, 0.0, 0.5, 0.5)],
        goods_classes=["30"],
        k=3,
    )
    res = pipeline.search(req)

    assert res.query.k == 3
    assert res.query.boxes == 1
    assert any(item.trademark_id == "T001" for item in res.image_topk.adjacent)
    assert res.image_topk.registered[0].trademark_id == "T001"
    assert res.text_topk.adjacent[0].trademark_id == "T001"


def test_pipeline_marks_non_adjacent_goods():
    pipeline = SearchPipeline()
    req = SearchRequest(
        image_b64=encode_image("Moonlight cafe dessert coffee night"),
        goods_classes=["01"],
        k=2,
    )
    res = pipeline.search(req)

    assert res.image_topk.non_adjacent
    top_id = res.image_topk.non_adjacent[0].trademark_id
    assert top_id in {"T003", "T004", "T002"}
    assert not res.image_topk.adjacent
