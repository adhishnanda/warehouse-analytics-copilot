"""One-command setup: seed the warehouse, build the retrieval indices, and
warm the reranker's model cache.

Usage: uv run python scripts/seed_and_index.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.seed_warehouse import seed  # noqa: E402
from src.config import DUCKDB_PATH, TPCH_SCALE_FACTOR  # noqa: E402
from src.retrieval.indexer import build_index, save_index  # noqa: E402
from src.retrieval.reranker import Reranker  # noqa: E402


def warm_reranker() -> None:
    """Force the cross-encoder's weights to download and cache now, at
    build time, instead of on the first real /ask request.

    build_index() above already warms the embedding model, but the
    reranker is a separate model that's only constructed lazily on the
    first .rerank() call (see reranker.py) - without this, that first
    live query after any deploy has to fetch the cross-encoder's weights
    from the Hugging Face Hub at runtime, over a free-tier host's
    throttled network and CPU. Observed live on Render: that alone made
    the first /ask request after a deploy hang for several minutes.
    """
    _ = Reranker().model


def main() -> None:
    seed(DUCKDB_PATH, TPCH_SCALE_FACTOR)

    print("Building retrieval indices...")
    index = build_index()
    save_index(index)
    print(f"Indexed {len(index['documents'])} semantic layer documents")

    print("Warming reranker model cache...")
    warm_reranker()
    print("Reranker model cached")


if __name__ == "__main__":
    main()
