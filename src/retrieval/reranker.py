"""Cross-encoder reranking over retrieved semantic layer chunks.

Retrieval (keyword/vector/hybrid) scores a query against each document
independently, which is fast but coarse. A cross-encoder scores the query
and document together, which is slower but far more precise — so it's used
as a second pass over a small candidate set, not as the first-pass search.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.retrieval.indexer import Document

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_LLM_RERANK_SYSTEM_PROMPT = (
    "You are the reranking step in a text-to-SQL system's retrieval "
    "pipeline. You are given a business question and a numbered list of "
    "candidate documents (table or metric descriptions). Return the "
    "candidate numbers ordered from most to least relevant to the "
    "question, as a comma-separated list of integers and nothing else."
)


class Reranker:
    """backend="local" (default) uses a local cross-encoder - this is what
    the retrieval evaluation (PROJECT_PLAN.md Section 7) was measured
    against.

    backend="openai" reranks via a chat completion instead, since OpenAI
    has no cross-encoder/rerank endpoint. Used only on the deployed
    instance to keep torch off it entirely - see the matching note in
    retriever.py and RETRIEVAL_BACKEND in src/config.py.
    """

    def __init__(self, model_name: str = RERANKER_MODEL_NAME, backend: str = "local"):
        self.model_name = model_name
        self.backend = backend
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            # Imported here, not at module level - see the matching comment
            # in indexer.py's build_index. Keeps torch out of process
            # startup entirely; it's only paid for on the first real rerank.
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self, query: str, candidates: list[tuple[Document, float]], k: int = 5
    ) -> list[tuple[Document, float]]:
        if not candidates:
            return []
        if self.backend == "openai":
            return self._rerank_llm(query, candidates, k)

        pairs = [(query, doc.text) for doc, _score in candidates]
        scores = self.model.predict(pairs)

        reranked = sorted(
            zip((doc for doc, _score in candidates), scores),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [(doc, float(score)) for doc, score in reranked[:k]]

    def _rerank_llm(
        self, query: str, candidates: list[tuple[Document, float]], k: int
    ) -> list[tuple[Document, float]]:
        """Reranks via a chat completion instead of a local cross-encoder.
        Falls back to the unreranked top-k on any parsing or API failure,
        the same fail-open approach rewrite_query already uses for its own
        backend, since reranking is an accuracy improvement, not a
        required step.
        """
        from src.llm_client import ApiUnavailableError, chat_openai

        numbered = "\n".join(f"{i + 1}. {doc.text}" for i, (doc, _score) in enumerate(candidates))
        user_content = f"Question: {query}\n\nCandidates:\n{numbered}"

        fallback = list(candidates[:k])
        try:
            reply = chat_openai(_LLM_RERANK_SYSTEM_PROMPT, user_content).content
        except ApiUnavailableError:
            return fallback

        order = [int(n) for n in re.findall(r"\d+", reply)]
        seen: set[int] = set()
        ranked: list[tuple[Document, float]] = []
        for n in order:
            if n in seen or not (1 <= n <= len(candidates)):
                continue
            seen.add(n)
            doc, _score = candidates[n - 1]
            # Not a real relevance score - the LLM returns an order, not a
            # number - this just preserves rank order for callers/logs
            # that display it, descending from 1.0.
            ranked.append((doc, round(1.0 - len(ranked) * 0.01, 3)))
            if len(ranked) == k:
                break

        return ranked if ranked else fallback
