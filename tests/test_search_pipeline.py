from app.schemas.search import SearchRequest
from app.pipelines.search_pipeline import SearchPipeline


def test_search_pipeline_returns_results():
    pipeline = SearchPipeline()
    req = SearchRequest(text="example", topn=3)
    res = pipeline.search(req)
    assert len(res.results) == 3


def test_search_pipeline_accepts_image_and_class():
    pipeline = SearchPipeline()
    req = SearchRequest(text="sample", class_code="30", image="abc", topn=1)
    res = pipeline.search(req)
    assert len(res.results) == 1
