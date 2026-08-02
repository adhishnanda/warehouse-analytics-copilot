"""Cross-encoder reranking over retrieved semantic layer chunks.

Retrieval (keyword/vector/hybrid) scores a query against each document
independently, which is fast but coarse. A cross-encoder scores the query
and document together, which is slower but far more precise — so it's used
as a second pass over a small candidate set, not as the first-pass search.
"""

from __future__ import annotations

from sentence_transformers import CrossEncoder

from src.retrieval.indexer import Document

RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    def __init__(self, model_name: str = RERANKER_MODEL_NAME):
        self.model_name = model_name
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self, query: str, candidates: list[tuple[Document, float]], k: int = 5
    ) -> list[tuple[Document, float]]:
        if not candidates:
            return []

        pairs = [(query, doc.text) for doc, _score in candidates]
        scores = self.model.predict(pairs)

        reranked = sorted(
            zip((doc for doc, _score in candidates), scores),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [(doc, float(score)) for doc, score in reranked[:k]]
