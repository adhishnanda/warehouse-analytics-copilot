# Session Log

## 2026-08-02 — Session 1

**Scope planned:** Week 1, Days 1-3 (repo skeleton + dataset/star schema,
semantic layer YAML, baseline keyword + vector retrieval), extended
progressively through Day 4 (query rewriting), Day 5 (cross-encoder
reranking), and Days 6-7 (agent loop + guardrails) as each prior day
finished with time still available.

**Scope built:** Days 1-7, complete and tested. All of Week 1 is done.
No scope cuts.

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

**Days 6-7 — agent loop and guardrails**
- `src/llm_client.py`: extracted the Ollama chat-request/timeout/error
  handling that Day 4's rewriter already had into one shared module,
  since the SQL generator needed the identical pattern — refactored
  `rewriter.py` to use it and re-ran its tests to confirm no regression.
- `src/db/duckdb_client.py`: `get_connection()` opens DuckDB with
  `read_only=True`. Verified directly (not just asserted) that this
  blocks CREATE/INSERT/UPDATE/DELETE/DROP even when guardrail checks are
  bypassed entirely — this is the outermost, connection-level safety
  layer, independent of the statement-level checks below.
- `src/agent/guardrails.py`: `check_select_only` (single statement,
  starts with SELECT/WITH, no write/DDL/admin keywords, no semicolon
  stacking), `apply_row_limit` (wraps every query in an outer
  `SELECT * FROM (...) LIMIT max_rows + 1` so truncation can be detected
  rather than guessed), and `run_guarded_query` (executes on a watchdog
  thread and calls `con.interrupt()` if it exceeds the timeout). Timeout
  behaviour was calibrated empirically before writing tests: a full
  self-cross-join of `fact_orders` (600k x 600k rows) reliably takes
  ~21s, and a 1.0s timeout interrupts it in ~1.0s, with the connection
  confirmed still usable immediately afterward. 27 tests, including
  parametrised rejection of 13 different disallowed statement shapes.
- `src/agent/tools.py`: `search_schema` composes Days 3-5 (rewrite ->
  hybrid_search -> rerank) into one call; `run_sql` wraps
  `run_guarded_query`; `validate_result` is a heuristic, not an LLM
  call — rejects empty/all-NULL results, and additionally checks that
  any question naming a "rate"/"share"/"percentage" gets back a value in
  [0, 1], since that's how every rate metric in `metrics.yml` is actually
  defined. This caught nothing artificial — it's built directly off the
  real metric definitions from Day 2.
- `src/agent/loop.py`: `generate_sql` prompts the local Ollama model with
  the retrieved context and asks for one SQL statement in a fenced code
  block; `answer_question` runs retrieve -> generate -> execute ->
  validate, retrying up to `MAX_ATTEMPTS = 2` with the previous error fed
  back into the next generation attempt.
- One real bug caught by manual end-to-end testing before writing formal
  tests: the SQL-extraction regex required a closing ` ```sql ` fence,
  but the local model sometimes doesn't close it. This silently left the
  fence markers inside the "SQL", which then failed the SELECT-only
  guardrail for the wrong reason (looked like a rejected write, was
  actually a parsing bug). Fixed by stripping fences from either end
  independently rather than requiring both — added directly to the
  regression tests (`test_extract_sql`, parametrised on closed/unclosed/
  no-fence/language-tagged inputs).
- `tests/test_agent_loop.py`: mixes deterministic tests (LLM call
  monkeypatched, so retry-stops-on-success / retries-on-guardrail-
  violation / stops-immediately-if-backend-down are verified without
  depending on model quality) with real end-to-end tests against the
  live Ollama backend and the actual warehouse (skipped if Ollama isn't
  reachable).
- Real end-to-end run against `llama3` (local, zero cost) on three
  questions, observed directly, not cherry-picked: "How many orders do
  we have in total?" -> succeeded, 150,000. "What is our repeat customer
  rate?" -> succeeded, 0.6665. "What is total revenue by region?" ->
  **failed** after both attempts — the model hallucinated column names
  (`key` instead of `nation_key`, `region` instead of `region_name`) on
  both tries despite correct context being retrieved. The guardrails
  caught each as a genuine DuckDB binder error, fed it back, and the
  system correctly reported failure rather than a wrong answer. This is
  an honest, expected limitation of an 8B local model on a join-heavy
  question, not a bug — and it's exactly the kind of result Week 2's
  LLM evaluation and Tier-3 ablation are designed to measure formally,
  rather than anecdotally as here.

### Measured (real numbers from this session)

- `fact_orders`: 600,572 rows; `dim_customer`: 15,000; `dim_product`:
  20,000; `dim_date`: 2,553; `dim_region`: 25; `dim_supplier`: 1,000
  (TPC-H scale factor 0.1).
- Test suite: **110/110 passing** (`uv run pytest`) — 21 warehouse-schema,
  15 semantic-layer, 9 retrieval, 4 query-rewriting, 5 reranking, 6
  duckdb-client, 27 guardrails, 10 agent-tools, 11 agent-loop, 2
  llm-client.
- Three real (uncherry-picked) end-to-end agent runs against local
  `llama3`: 2/3 succeeded with correct answers (order count 150,000;
  repeat customer rate 0.6665); 1/3 failed cleanly after exhausting
  retries on a join-heavy question, with the failure mode (hallucinated
  column names) captured accurately by the guardrails rather than
  silently producing a wrong number. This is anecdotal, not a measured
  accuracy rate — Week 2, Day 11 produces the real number.
- No retrieval evaluation numbers (hit rate/MRR) yet — needs the golden
  question set. No formal LLM evaluation numbers yet (Section 7.3: model
  x prompt comparison) — only local Ollama calls made this session, no
  paid model, consistent with cost discipline.

### What's next

Week 1 is complete — repo, warehouse, semantic layer, hybrid retrieval,
query rewriting, reranking, agent loop, and tested guardrails are all in
place. Week 2, in order (see `PROJECT_PLAN.md` Section 8):
1. **Days 8-9** — write the 50 golden question-SQL pairs across the three
   difficulty tiers. This defines what "correct" means before any
   evaluation code is written against it, and should draw on the real
   failure mode observed above (join-heavy, multi-table questions are
   where this system is currently weakest).
2. **Day 10** — retrieval evaluation: keyword vs vector vs hybrid vs
   hybrid+rerank, hit rate + MRR, stated winner.
3. **Day 11** — LLM evaluation: 2 models x 2 prompts, execution accuracy,
   stated winner. This is also where a paid model is first considered
   for the final reproducible runs — flag before making any paid call,
   per `CLAUDE.md` rule 5.
4. **Day 12** — measure self-correction lift (retry loop on vs off).
5. **Days 13-14** — Tier-3 retrieval ablation (the headline result) and
   error analysis write-up.

Nothing from Days 1-7 is left unfinished. No paid API calls made this
session (cost discipline honoured — only local DuckDB, a local
open-weights embedding model, and a local Ollama model were used).
