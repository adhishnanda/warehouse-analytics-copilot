# Session Log

## 2026-08-02 — Session 1

**Scope planned:** Week 1, Days 1-3 (repo skeleton + dataset/star schema,
semantic layer YAML, baseline keyword + vector retrieval), extended to
Day 4 (query rewriting) and Day 5 (cross-encoder reranking) once earlier
days finished with time still available.

**Scope built:** Days 1-5, complete and tested. No scope cuts.

### What was built

**Day 1 — repo skeleton, environment, dataset, star schema**
- Full repository structure per `PROJECT_PLAN.md` Section 9.
- Python pinned to 3.13.7 via `uv` (3.14, the system default, is too new
  for reliable `duckdb`/`torch`/`sentence-transformers` wheels).
- Dataset decision: **TPC-H via DuckDB's built-in `dbgen`**, not the UK
  Online Retail dataset — zero external downloads (fully reproducible from
  a clone), deterministic generation at any scale factor, and its native
  tables map directly onto a fact + 5-dimension star schema without messy
  real-world cleanup.
- `data/seed_warehouse.py`: generates TPC-H at scale factor 0.1 and
  reshapes it into `fact_orders` (line-item grain) plus five dimensions —
  `dim_customer`, `dim_supplier`, `dim_product`, `dim_date`, `dim_region`
  (nation-grain, with region as an attribute — TPC-H's `region` table alone
  is only 5 rows, too coarse to be a useful independent join target). Raw
  TPC-H tables are dropped after reshaping so only the governed star schema
  is queryable.
- `Dockerfile` + `docker-compose.yml`: single consolidated compose file
  (per the rubric requirement), currently one `seed` service that builds
  the pinned environment and runs the seed script. Verified working
  end-to-end via `docker compose run --rm seed` — same row counts as the
  local run. Later weeks add `api`, `ui`, `kestra` services to this same
  file rather than introducing separate compose files.
- `tests/test_warehouse_schema.py`: 21 tests — table existence, row counts,
  primary key uniqueness on every dimension, `dim_date` contiguity, and
  every foreign key in `fact_orders` (customer/supplier/product/order
  date/ship date) resolves with zero orphans.

**Day 2 — semantic layer YAML**
- `semantic_layer/tables/*.yml`: one file per table (description, grain,
  per-column type + description, join keys, caveats) for all 6 tables.
- `semantic_layer/metrics.yml`: 5 business metrics, each with a prose
  description and backing SQL — `total_revenue`, `order_count`,
  `average_order_value`, `repeat_customer_rate`, `average_discount_rate`.
  Deliberately did *not* define a "return rate" metric: TPC-H's
  `l_returnflag` is a synthetic accounting flag from the data generator,
  and its exact real-world semantics weren't confident enough to assert
  as a named business metric — documented as a caveat on the column
  instead of guessing.
- `tests/test_semantic_layer.py`: 15 tests. The one that matters most —
  every documented column is checked against `PRAGMA table_info` on the
  actual DuckDB tables, in both directions (nothing documented that
  doesn't exist, nothing existing that isn't documented), so the YAML
  cannot silently drift from the real schema. Every metric's SQL is also
  executed against the real warehouse and checked for a non-null result.

**Day 3 — baseline keyword and vector retrieval**
- `src/retrieval/indexer.py`: renders each table doc and metric into a
  flat text chunk (11 documents total), builds a BM25 keyword index
  (`rank-bm25`) and a vector index (`sentence-transformers`,
  `all-MiniLM-L6-v2`, run locally — no API cost), persists both to
  `data/indices/` (gitignored, rebuilt via `scripts/seed_and_index.py`).
- `src/retrieval/retriever.py`: `keyword_search`, `vector_search`, and
  `hybrid_search` (normalized BM25 + cosine, weighted by `alpha`).
- `scripts/seed_and_index.py`: one-command setup — seeds the warehouse and
  builds both indices. Verified working from a clean state.
- `tests/test_retrieval.py`: 9 tests, including one that specifically
  demonstrates *why* vector search earns its place — the query "how much
  money have we brought in overall" shares no keywords with the
  `total_revenue` doc text, and vector search still retrieves it in the
  top 3. This is a functional sanity check, not the full retrieval
  evaluation table (that needs the 50-question golden set, which is a
  Week 2 task) — hit rate / MRR numbers are not yet measured and must not
  be quoted anywhere until Week 2, Day 10 produces them.

**Day 4 — query rewriting**
- `src/retrieval/rewriter.py`: `rewrite_query(question)` calls a local
  Ollama model (`llama3`, already pulled — zero cost, no API key) with a
  system prompt instructing it to expand abbreviations and surface the
  business concepts (revenue, discount, order count, repeat customers,
  region, supplier, ship date vs order date) a question is really asking
  about, without answering it. Falls back to returning the original
  question unchanged if the backend is unreachable — rewriting is an
  optimization on top of retrieval, not a hard dependency.
- One debugging note worth keeping: the first end-to-end call timed out at
  60s (model cold start / first invocation in that process), but a repeat
  call with the same prompt returned in under 5s. Default timeout raised
  from 15s to 30s to absorb this without treating it as a real failure.
- `tests/test_rewriter.py`: 4 tests — deterministic fallback-on-unreachable
  test (no backend needed), plus three real-backend tests (skipped if
  Ollama isn't reachable) checking non-empty output, that an abbreviated
  question ("rev by region last qtr") gets rewritten to mention "revenue"
  and "region", and that the rewrite never contains digits or a "%" (i.e.
  it reformulates the question, it doesn't fabricate an answer to it).

**Day 5 — cross-encoder reranking**
- `src/retrieval/reranker.py`: `Reranker.rerank(query, candidates, k)` scores
  each (query, document) pair jointly with `cross-encoder/ms-marco-MiniLM-L-6-v2`
  (local, no API cost) and returns the top-k by that score. Takes hybrid
  search's candidate list as input rather than searching independently —
  reranking is a precision-focused second pass over a small candidate set,
  not a first-pass retrieval method.
- `tests/test_reranker.py`: 5 tests, including one that demonstrates the
  actual value of reranking rather than just checking it runs — for "when
  did suppliers ship items late", hybrid search's top result is
  `dim_supplier` (lexical/embedding match on "suppliers"), but shipping
  lateness is documented on `fact_orders` (`ship_date_key`), not on
  `dim_supplier`. The cross-encoder reorders `fact_orders` to first place.
  This mirrors the paraphrase test from Day 3's retrieval suite — a test
  that would fail if the technique weren't actually doing anything.

### Measured (real numbers from this session)

- `fact_orders`: 600,572 rows; `dim_customer`: 15,000; `dim_product`:
  20,000; `dim_date`: 2,553; `dim_region`: 25; `dim_supplier`: 1,000
  (TPC-H scale factor 0.1).
- Test suite: **54/54 passing** (`uv run pytest`) — 21 warehouse-schema,
  15 semantic-layer, 9 retrieval, 4 query-rewriting, 5 reranking.
- No retrieval evaluation numbers (hit rate/MRR) yet — that requires the
  golden question set, not built this session. No LLM evaluation numbers
  yet in the Section 7.3 sense (model x prompt comparison) — the only LLM
  calls made this session were local Ollama calls for the query rewriter,
  not a paid model, consistent with cost discipline.

### What's next

Week 1, Days 6-7:
- Agent loop (`search_schema`, `run_sql`, `validate_result` tools) and
  `src/agent/guardrails.py` (read-only connection, SELECT-only whitelist,
  row limits, timeout) — must be tested, not just implemented, per the
  non-negotiable rules in `CLAUDE.md`. `search_schema` should compose the
  Day 3-5 pieces built this session: rewrite -> hybrid_search -> rerank.
- This closes out Week 1 entirely (all three "best practice" retrieval
  rubric items — hybrid search, query rewriting, reranking — are now
  implemented; Week 2 is where they get formally evaluated against the
  golden question set).

Nothing from Days 1-5 is left unfinished. No paid API calls made this
session (cost discipline honoured — only local DuckDB, a local
open-weights embedding model, and a local Ollama model were used).
