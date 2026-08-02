"""One-command setup: seed the warehouse and build the retrieval indices.

Usage: uv run python scripts/seed_and_index.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.seed_warehouse import seed  # noqa: E402
from src.config import DUCKDB_PATH, TPCH_SCALE_FACTOR  # noqa: E402
from src.retrieval.indexer import build_index, save_index  # noqa: E402


def main() -> None:
    seed(DUCKDB_PATH, TPCH_SCALE_FACTOR)

    print("Building retrieval indices...")
    index = build_index()
    save_index(index)
    print(f"Indexed {len(index['documents'])} semantic layer documents")


if __name__ == "__main__":
    main()
