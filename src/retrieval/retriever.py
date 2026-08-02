"""Keyword, vector, and hybrid search over the semantic layer index."""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

from src.retrieval.indexer import INDEX_PATH, Document, load_index, tokenize


def _normalize(scores: np.ndarray) -> np.ndarray:
    if scores.max() == scores.min():
        return np.zeros_like(scores)
    return (scores - scores.min()) / (scores.max() - scores.min())


class Retriever:
    """Loads a persisted semantic layer index and searches it.

    hybrid_search combines normalized BM25 (keyword) and cosine (vector)
    scores. alpha=1.0 is pure vector, alpha=0.0 is pure keyword.
    """

    def __init__(self, index_path=INDEX_PATH):
        self.index = load_index(index_path)
        self.documents: list[Document] = self.index["documents"]
        self.bm25 = self.index["bm25"]
        self.embeddings: np.ndarray = self.index["embeddings"]
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self.index["embedding_model_name"])
        return self._model

    def _bm25_scores(self, query: str) -> np.ndarray:
        return np.asarray(self.bm25.get_scores(tokenize(query)))

    def _vector_scores(self, query: str) -> np.ndarray:
        query_embedding = self.model.encode([query], normalize_embeddings=True)[0]
        return self.embeddings @ query_embedding

    def _top_k(self, scores: np.ndarray, k: int) -> list[tuple[Document, float]]:
        ranked = np.argsort(scores)[::-1][:k]
        return [(self.documents[i], float(scores[i])) for i in ranked]

    def keyword_search(self, query: str, k: int = 5) -> list[tuple[Document, float]]:
        return self._top_k(self._bm25_scores(query), k)

    def vector_search(self, query: str, k: int = 5) -> list[tuple[Document, float]]:
        return self._top_k(self._vector_scores(query), k)

    def hybrid_search(self, query: str, k: int = 5, alpha: float = 0.5) -> list[tuple[Document, float]]:
        combined = alpha * _normalize(self._vector_scores(query)) + (1 - alpha) * _normalize(
            self._bm25_scores(query)
        )
        return self._top_k(combined, k)
