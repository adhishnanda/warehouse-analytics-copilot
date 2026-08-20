"""Keyword, vector, and hybrid search over the semantic layer index."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from src.retrieval.indexer import INDEX_PATH, Document, load_index, tokenize

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"


def _normalize(scores: np.ndarray) -> np.ndarray:
    if scores.max() == scores.min():
        return np.zeros_like(scores)
    return (scores - scores.min()) / (scores.max() - scores.min())


class Retriever:
    """Loads a persisted semantic layer index and searches it.

    hybrid_search combines normalized BM25 (keyword) and cosine (vector)
    scores. alpha=1.0 is pure vector, alpha=0.0 is pure keyword.

    backend="local" (default) uses the sentence-transformers embeddings
    baked into the index at build time (indexer.py's build_index). This is
    what the retrieval evaluation (PROJECT_PLAN.md Section 7) was measured
    against, and stays the default everywhere.

    backend="openai" recomputes corpus and query embeddings via OpenAI's
    embeddings API instead, ignoring the index's baked-in local embeddings
    entirely. Exists only to keep torch (and the CPU/memory cost of
    loading it) off the deployed instance: Render's free tier gives this
    service 0.15 CPU, and the local embedding model alone was observed to
    starve that budget for minutes on a single request. See
    RETRIEVAL_BACKEND in src/config.py and SESSION_LOG.md.
    """

    def __init__(self, index_path=INDEX_PATH, backend: str = "local"):
        self.index = load_index(index_path)
        self.documents: list[Document] = self.index["documents"]
        self.bm25 = self.index["bm25"]
        self.embeddings: np.ndarray = self.index["embeddings"]
        self.backend = backend
        self._model: SentenceTransformer | None = None
        self._openai_corpus_embeddings: np.ndarray | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            # Imported here, not at module level - see the matching comment
            # in indexer.py's build_index. Keeps torch out of process
            # startup entirely; it's only paid for on the first real search.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.index["embedding_model_name"])
        return self._model

    def _openai_embed(self, texts: list[str]) -> np.ndarray:
        from src.llm_client import embed_openai

        vectors = np.asarray(embed_openai(texts, model=OPENAI_EMBEDDING_MODEL))
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1, norms)

    def _corpus_embeddings(self) -> np.ndarray:
        if self.backend != "openai":
            return self.embeddings
        if self._openai_corpus_embeddings is None:
            # Computed once per process, not baked into the index at build
            # time - keeps the OpenAI key out of the Docker build step
            # (which may not have it available), and the corpus is tiny
            # (a handful of short documents), so the cost is negligible.
            self._openai_corpus_embeddings = self._openai_embed([doc.text for doc in self.documents])
        return self._openai_corpus_embeddings

    def _bm25_scores(self, query: str) -> np.ndarray:
        return np.asarray(self.bm25.get_scores(tokenize(query)))

    def _vector_scores(self, query: str) -> np.ndarray:
        if self.backend == "openai":
            from src.llm_client import ApiUnavailableError

            try:
                query_embedding = self._openai_embed([query])[0]
                corpus_embeddings = self._corpus_embeddings()
            except ApiUnavailableError:
                # Fail open, the same way rewrite_query and the LLM
                # reranker already do: retrieval degrades to keyword-only
                # (BM25) ranking rather than crashing the whole /ask
                # request on an API hiccup - see hybrid_search/_normalize,
                # an all-zero vector score contributes nothing to the mix.
                return np.zeros(len(self.documents))
            return corpus_embeddings @ query_embedding

        query_embedding = self.model.encode([query], normalize_embeddings=True)[0]
        return self._corpus_embeddings() @ query_embedding

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
