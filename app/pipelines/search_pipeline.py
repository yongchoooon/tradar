from app.schemas.search import SearchRequest, SearchResponse, SearchResult


class SearchPipeline:
    """Simplified search pipeline placeholder."""

    def search(self, req: SearchRequest) -> SearchResponse:
        """Return dummy results for the given request."""
        dummy = SearchResult(trademark_id="000000", score=0.0)
        results = [dummy] * req.topn
        return SearchResponse(results=results)
