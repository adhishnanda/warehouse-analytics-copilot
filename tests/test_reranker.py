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
from src.retrieval.indexer import INDEX_PATH
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
