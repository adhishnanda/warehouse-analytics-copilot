"""Functional sanity tests for keyword, vector, and hybrid retrieval over
the semantic layer index.

These are not the full retrieval evaluation (that needs the golden question
set — Week 2) — just checks that each retrieval mode behaves sensibly on a
handful of representative queries, and specifically that vector search
finds paraphrased matches a keyword-only baseline would miss.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import src.llm_client as llm_client
from src.config import OPENAI_API_KEY
from src.retrieval.indexer import INDEX_PATH, build_index, load_documents, save_index
from src.retrieval.retriever import Retriever

pytestmark = pytest.mark.skipif(
    not INDEX_PATH.exists(),
    reason="semantic layer index not built yet — run python -m src.retrieval.indexer",
)
requires_openai_key = pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY not set")


@pytest.fixture(scope="module")
def retriever():
    return Retriever()


def test_load_documents_covers_all_tables_and_metrics():
    documents = load_documents()
    doc_ids = {doc.doc_id for doc in documents}

    assert len(documents) == 11
    for table in ["fact_orders", "dim_customer", "dim_product", "dim_date", "dim_region", "dim_supplier"]:
        assert f"table:{table}" in doc_ids
    for metric in ["total_revenue", "order_count", "average_order_value", "repeat_customer_rate", "average_discount_rate"]:
        assert f"metric:{metric}" in doc_ids


def test_keyword_search_finds_exact_term_match(retriever):
    results = retriever.keyword_search("repeat customer rate", k=3)
    top_ids = [doc.doc_id for doc, _score in results]
    assert "metric:repeat_customer_rate" in top_ids


def test_keyword_search_scores_are_descending(retriever):
    results = retriever.keyword_search("revenue", k=5)
    scores = [score for _doc, score in results]
    assert scores == sorted(scores, reverse=True)


def test_vector_search_finds_paraphrased_match(retriever):
    # No shared keywords with "total_revenue" doc text ("revenue", "net", "orders"),
    # but semantically the same question — this is what a keyword-only baseline
    # is expected to miss and vector search is expected to catch.
    results = retriever.vector_search("how much money have we brought in overall", k=3)
    top_ids = [doc.doc_id for doc, _score in results]
    assert "metric:total_revenue" in top_ids


def test_vector_search_scores_are_descending(retriever):
    results = retriever.vector_search("revenue", k=5)
    scores = [score for _doc, score in results]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_search_returns_k_results(retriever):
    results = retriever.hybrid_search("customers who order more than once", k=4)
    assert len(results) == 4


def test_hybrid_search_finds_relevant_doc_for_metric_question(retriever):
    results = retriever.hybrid_search("what is our repeat customer rate", k=3)
    top_ids = [doc.doc_id for doc, _score in results]
    assert "metric:repeat_customer_rate" in top_ids


def test_hybrid_search_finds_relevant_table_for_join_question(retriever):
    results = retriever.hybrid_search("which suppliers are based in which region", k=4)
    top_ids = [doc.doc_id for doc, _score in results]
    assert "table:dim_supplier" in top_ids
    assert "table:dim_region" in top_ids


def test_build_index_is_reproducible_in_document_count(tmp_path):
    index = build_index()
    assert len(index["documents"]) == 11
    assert index["embeddings"].shape[0] == 11

    saved_path = tmp_path / "index.pkl"
    save_index(index, path=saved_path)
    assert saved_path.exists()


# --- backend="openai" (RETRIEVAL_BACKEND, see retriever.py's docstring) ---


def test_openai_backend_computes_corpus_embeddings_once(monkeypatch):
    calls = {"n": 0}

    def fake_embed(texts, model="text-embedding-3-small", timeout=30.0):
        calls["n"] += 1
        return [[float(i), 1.0] for i in range(len(texts))]

    monkeypatch.setattr(llm_client, "embed_openai", fake_embed)

    retriever = Retriever(backend="openai")
    retriever.vector_search("revenue", k=3)
    retriever.vector_search("orders", k=3)

    # One call embeds the whole corpus, cached after that; one more call
    # per query search - not eleven calls per search.
    assert calls["n"] == 3


def test_openai_backend_returns_k_results(monkeypatch):
    monkeypatch.setattr(llm_client, "embed_openai", lambda texts, **_kw: [[1.0, 0.0] for _ in texts])

    retriever = Retriever(backend="openai")
    results = retriever.hybrid_search("revenue", k=4)
    assert len(results) == 4


@requires_openai_key
def test_openai_backend_finds_paraphrased_match_for_real():
    # Same paraphrase case test_vector_search_finds_paraphrased_match uses
    # for the local backend - confirms the API-backed swap isn't just
    # structurally correct but actually finds the right document.
    retriever = Retriever(backend="openai")
    results = retriever.vector_search("how much money have we brought in overall", k=3)
    top_ids = [doc.doc_id for doc, _score in results]
    assert "metric:total_revenue" in top_ids
