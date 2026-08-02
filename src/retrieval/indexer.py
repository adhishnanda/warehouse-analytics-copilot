"""Build keyword (BM25) and vector (sentence-transformer) indices over the
semantic layer, and persist them so the retriever can load without
rebuilding on every request.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from src.config import REPO_ROOT, SEMANTIC_LAYER_DIR

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
INDEX_DIR = REPO_ROOT / "data" / "indices"
INDEX_PATH = INDEX_DIR / "semantic_layer_index.pkl"


@dataclass
class Document:
    doc_id: str
    doc_type: str  # "table" or "metric"
    name: str
    text: str


def _render_table_doc(path: Path) -> Document:
    doc = yaml.safe_load(path.read_text())
    columns_text = "\n".join(
        f"  - {col}: {meta['description']}" for col, meta in doc["columns"].items()
    )
    caveats_text = "\n".join(f"  - {c}" for c in doc.get("caveats", []))
    text = (
        f"Table: {doc['table']}\n"
        f"Description: {doc['description'].strip()}\n"
        f"Grain: {doc['grain'].strip()}\n"
        f"Columns:\n{columns_text}\n"
        f"Caveats:\n{caveats_text}"
    )
    return Document(doc_id=f"table:{doc['table']}", doc_type="table", name=doc["table"], text=text)


def _render_metric_docs(path: Path) -> list[Document]:
    metrics = yaml.safe_load(path.read_text())
    docs = []
    for name, meta in metrics.items():
        text = (
            f"Metric: {name}\n"
            f"Description: {meta['description'].strip()}\n"
            f"SQL:\n{meta['sql'].strip()}"
        )
        docs.append(Document(doc_id=f"metric:{name}", doc_type="metric", name=name, text=text))
    return docs


def load_documents() -> list[Document]:
    documents = [
        _render_table_doc(path) for path in sorted((SEMANTIC_LAYER_DIR / "tables").glob("*.yml"))
    ]
    documents.extend(_render_metric_docs(SEMANTIC_LAYER_DIR / "metrics.yml"))
    return documents


def tokenize(text: str) -> list[str]:
    return text.lower().replace("_", " ").split()


def build_index(documents: list[Document] | None = None) -> dict:
    if documents is None:
        documents = load_documents()

    tokenized_corpus = [tokenize(doc.text) for doc in documents]
    bm25 = BM25Okapi(tokenized_corpus)

    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    embeddings = model.encode([doc.text for doc in documents], normalize_embeddings=True)

    return {
        "documents": documents,
        "bm25": bm25,
        "embeddings": np.asarray(embeddings),
        "embedding_model_name": EMBEDDING_MODEL_NAME,
    }


def save_index(index: dict, path: Path = INDEX_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(index, f)


def load_index(path: Path = INDEX_PATH) -> dict:
    with open(path, "rb") as f:
        return pickle.load(f)
