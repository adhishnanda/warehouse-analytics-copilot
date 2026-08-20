"""Unit test for seed_and_index.py's reranker warm-up step.

Doesn't exercise seed() or build_index() (both slow/heavy and already
covered elsewhere) - just checks warm_reranker() actually touches the
model property, since that access is what forces the cross-encoder's
weights to download at build time instead of on the first live request.
See tests/test_reranker.py for the real functional reranking tests.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scripts.seed_and_index as seed_and_index


def test_warm_reranker_accesses_model_property(monkeypatch):
    accessed = {"count": 0}

    class FakeReranker:
        @property
        def model(self):
            accessed["count"] += 1
            return object()

    monkeypatch.setattr(seed_and_index, "Reranker", FakeReranker)

    seed_and_index.warm_reranker()

    assert accessed["count"] == 1
