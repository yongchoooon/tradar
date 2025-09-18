"""OpenSearch query helpers placeholder."""


def text_query(text: str) -> dict:  # pragma: no cover
    return {"query": {"match": {"title": text}}}
