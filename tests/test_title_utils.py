from app.schemas.search import QueryInfo, SearchResponse, SearchResult
from app.services.search_cache import SearchCache
from app.services.title_utils import localized_mark_title, normalize_mark_title


def test_normalize_mark_title_treats_missing_labels_as_empty() -> None:
    assert normalize_mark_title("") == ""
    assert normalize_mark_title("  ") == ""
    assert normalize_mark_title("(상표명 없음)") == ""
    assert normalize_mark_title("(No name)") == ""
    assert normalize_mark_title("T-RADAR") == "T-RADAR"


def test_localized_mark_title_uses_requested_language_for_missing_values() -> None:
    assert localized_mark_title("(상표명 없음)", "en") == "(No name)"
    assert localized_mark_title("(No name)", "ko") == "(상표명 없음)"
    assert localized_mark_title("T-RADAR", "en") == "T-RADAR"


def test_search_cache_removes_placeholder_titles_before_simulation() -> None:
    cache = SearchCache()
    response = SearchResponse(
        query=QueryInfo(k=1, text=None, goods_classes=[], group_codes=[]),
        image_top=[
            SearchResult(
                trademark_id="4020260000000",
                title="(상표명 없음)",
                status="등록",
                class_codes=["35"],
                app_no="4020260000000",
                image_sim=0.9,
                text_sim=0.1,
            )
        ],
        image_misc=[],
        text_top=[],
        text_misc=[],
    )

    search_id = cache.store(response)
    selection = cache.get(search_id).selections[("4020260000000", "image")]

    assert selection.title == ""
