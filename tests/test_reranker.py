"""Functional sanity tests for cross-encoder reranking.

Like test_retrieval.py, these are not the full retrieval evaluation (that
needs the golden question set — Week 2) — just checks reranking behaves
sensibly, and specifically that it can reorder hybrid search's top result
when the cross-encoder judges a different candidate more relevant.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import src.llm_client as llm_client
from src.llm_client import ApiUnavailableError, ChatCompletion
from src.retrieval.indexer import Document, INDEX_PATH
from src.retrieval.reranker import Reranker
from src.retrieval.retriever import Retriever

pytestmark = pytest.mark.skipif(
    not INDEX_PATH.exists(),
    reason="semantic layer index not built yet — run scripts/seed_and_index.py",
)


@pytest.fixture(scope="module")
def retriever():
    return Retriever()


@pytest.fixture(scope="module")
def reranker():
    return Reranker()


def test_rerank_empty_candidates_returns_empty(reranker):
    assert reranker.rerank("anything", [], k=5) == []


def test_rerank_returns_k_results_sorted_descending(retriever, reranker):
    candidates = retriever.hybrid_search("revenue by region", k=8)
    reranked = reranker.rerank("revenue by region", candidates, k=4)

    assert len(reranked) == 4
    scores = [score for _doc, score in reranked]
    assert scores == sorted(scores, reverse=True)


def test_rerank_finds_correct_metric_for_direct_question(retriever, reranker):
    query = "what is our repeat customer rate"
    candidates = retriever.hybrid_search(query, k=8)
    reranked = reranker.rerank(query, candidates, k=3)

    assert reranked[0][0].doc_id == "metric:repeat_customer_rate"


def test_rerank_finds_correct_metric_for_trend_question(retriever, reranker):
    query = "average order value trend"
    candidates = retriever.hybrid_search(query, k=8)
    reranked = reranker.rerank(query, candidates, k=3)

    assert reranked[0][0].doc_id == "metric:average_order_value"


def test_rerank_can_reorder_hybrid_top_result(retriever, reranker):
    # Hybrid's lexical/embedding match puts dim_supplier first (the query
    # names suppliers), but shipping lateness is actually documented on
    # fact_orders (ship_date_key), not on dim_supplier. The cross-encoder
    # is expected to judge fact_orders more relevant despite hybrid
    # ranking it second — this is the reordering reranking is for.
    query = "when did suppliers ship items late"
    candidates = retriever.hybrid_search(query, k=8)
    hybrid_top_id = candidates[0][0].doc_id

    reranked = reranker.rerank(query, candidates, k=5)
    rerank_top_id = reranked[0][0].doc_id

    assert hybrid_top_id == "table:dim_supplier"
    assert rerank_top_id == "table:fact_orders"
    assert rerank_top_id != hybrid_top_id


# --- backend="openai" (RETRIEVAL_BACKEND, see reranker.py's docstring) ---


def _fake_candidates(n: int) -> list[tuple[Document, float]]:
    return [
        (Document(doc_id=f"doc:{i}", doc_type="table", name=f"doc{i}", text=f"text {i}"), 0.0)
        for i in range(n)
    ]


def test_llm_rerank_reorders_by_returned_candidate_numbers(monkeypatch):
    candidates = _fake_candidates(3)
    monkeypatch.setattr(
        llm_client, "chat_openai", lambda *_a, **_kw: ChatCompletion(content="3, 1, 2")
    )

    reranker = Reranker(backend="openai")
    reranked = reranker.rerank("anything", candidates, k=3)

    assert [doc.doc_id for doc, _score in reranked] == ["doc:2", "doc:0", "doc:1"]


def test_llm_rerank_respects_k(monkeypatch):
    candidates = _fake_candidates(5)
    monkeypatch.setattr(
        llm_client, "chat_openai", lambda *_a, **_kw: ChatCompletion(content="1, 2, 3, 4, 5")
    )

    reranker = Reranker(backend="openai")
    reranked = reranker.rerank("anything", candidates, k=2)

    assert len(reranked) == 2


def test_llm_rerank_falls_back_to_original_order_on_unparseable_reply(monkeypatch):
    candidates = _fake_candidates(3)
    monkeypatch.setattr(llm_client, "chat_openai", lambda *_a, **_kw: ChatCompletion(content="no idea"))

    reranker = Reranker(backend="openai")
    reranked = reranker.rerank("anything", candidates, k=3)

    assert [doc.doc_id for doc, _score in reranked] == [doc.doc_id for doc, _score in candidates]


def test_llm_rerank_falls_back_to_original_order_when_api_unavailable(monkeypatch):
    candidates = _fake_candidates(3)

    def _raise(*_a, **_kw):
        raise ApiUnavailableError("down")

    monkeypatch.setattr(llm_client, "chat_openai", _raise)

    reranker = Reranker(backend="openai")
    reranked = reranker.rerank("anything", candidates, k=2)

    assert [doc.doc_id for doc, _score in reranked] == [doc.doc_id for doc, _score in candidates[:2]]


def test_llm_rerank_ignores_out_of_range_and_duplicate_numbers(monkeypatch):
    candidates = _fake_candidates(2)
    monkeypatch.setattr(
        llm_client, "chat_openai", lambda *_a, **_kw: ChatCompletion(content="9, 1, 1, 2")
    )

    reranker = Reranker(backend="openai")
    reranked = reranker.rerank("anything", candidates, k=2)

    assert [doc.doc_id for doc, _score in reranked] == ["doc:0", "doc:1"]
