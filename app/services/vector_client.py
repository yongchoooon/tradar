"""pgvector-based ANN helper routines."""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

from app.services import db
from app.services.embedding_utils import cosine


_IMAGE_TABLES = {
    "dino": ("image_embeddings_dino", True),  # pgvector <#> returns negative inner product
    "metaclip": ("image_embeddings_metaclip", True),
}

_TEXT_TABLE = ("text_embeddings_metaclip", True)


class VectorClient:
    """Convenience wrapper around pgvector ANN queries."""

    def search_image(self, space: str, vector: Sequence[float], topn: int) -> List[dict]:
        table_info = _IMAGE_TABLES.get(space)
        if not table_info:
            raise ValueError(f"Unsupported image space: {space}")
        return self._search(table_info, vector, topn)

    def search_text(self, vector: Sequence[float], topn: int) -> List[dict]:
        return self._search(_TEXT_TABLE, vector, topn)

    def get_image_embeddings(self, space: str, ids: Iterable[str]) -> Dict[str, List[float]]:
        table_info = _IMAGE_TABLES.get(space)
        if not table_info:
            raise ValueError(f"Unsupported image space: {space}")
        return self._fetch_vectors(table_info[0], ids)

    def get_text_embeddings(self, ids: Iterable[str]) -> Dict[str, List[float]]:
        return self._fetch_vectors(_TEXT_TABLE[0], ids)

    def cosine_scores(
        self, query: Sequence[float], embeddings: Dict[str, List[float]]
    ) -> Dict[str, float]:
        vec = list(query)
        return {key: cosine(vec, emb) for key, emb in embeddings.items()}

    def _search(
        self, table_info: tuple[str, bool], vector: Sequence[float], topn: int
    ) -> List[dict]:
        if topn <= 0:
            return []
        payload: List[dict] = []
        table, negate = table_info
        vector_literal = _to_vector_literal(vector)
        sql = (
            f"SELECT application_number, (vector <#> %s::vector) AS score "
            f"FROM {table} "
            f"ORDER BY vector <#> %s::vector {'ASC' if negate else 'DESC'} "
            f"LIMIT %s"
        )
        with db.get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (vector_literal, vector_literal, topn))
            for app_no, score in cur.fetchall():
                value = float(score)
                if negate:
                    value = -value
                payload.append({"id": app_no, "score": value})
        return payload

    def _fetch_vectors(self, table: str, ids: Iterable[str]) -> Dict[str, List[float]]:
        id_list = [tm_id for tm_id in ids if tm_id]
        if not id_list:
            return {}
        sql = (
            f"SELECT application_number, vector "
            f"FROM {table} "
            f"WHERE application_number = ANY(%s)"
        )
        results: Dict[str, List[float]] = {}
        with db.get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, (id_list,))
            for app_no, vector in cur.fetchall():
                results[app_no] = list(vector)
        return results


def _to_vector_literal(values: Sequence[float]) -> str:
    formatted = ",".join(f"{value:.12f}" for value in values)
    return f"[{formatted}]"
