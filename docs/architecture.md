# Architecture

This document explains the design decisions behind each major component,
not just what the code does; the code itself is the source of truth for
that.

## Why DuckDB

DuckDB is an embedded, single-file analytical database: no server process
to run, no credentials to manage, and it ships a deterministic TPC-H
generator (`CALL dbgen(sf=...)`) built in. That combination is what makes
the whole project reproducible from a clean clone with zero external
downloads or accounts: `data/seed_warehouse.py` generates the same data
on every machine, at every run, from `dbgen` alone. It's also read-only
capable at the connection level (`duckdb.connect(path, read_only=True)`),
which is the outermost layer of the guardrail design below, a property a
client-server database would need a separate role/grant system to get.

## Semantic layer format

`semantic_layer/tables/*.yml` (one file per table) and
`semantic_layer/metrics.yml` (business metrics) were chosen over
alternatives like embedding documentation as SQL comments, or generating
it from the schema automatically, for one reason: the point of the
project is that a human decides what a metric means and how grain works,
and the LLM is grounded in that decision rather than inferring it fresh
per question. YAML was picked over, say, a Python dict or a database
table for the docs themselves specifically because it's the format a real
analytics engineer would review and edit by hand. This is meant to read
like the kind of documentation a dbt or LookML project actually has, not
like a retrieval-system-specific artifact.

Two properties are enforced by tests, not just convention:

- **The YAML cannot drift from the real schema.** Every documented column
  is checked against the live warehouse's `PRAGMA table_info` in both
  directions (`tests/test_semantic_layer.py`): nothing documented that
  doesn't exist, nothing existing that isn't documented.
- **Every metric's SQL actually runs.** Each `metrics.yml` entry's `sql`
  is executed against the real warehouse in tests and checked for a
  non-null result, so a metric definition can't silently rot into broken
  SQL.

`metrics.yml` also carries an `answers_questions_like` field per metric:
short, generic phrasings a user might ask with. This exists because of a
retrieval evaluation finding (below): short, formulaic metric chunks gave
a cross-encoder reranker too little signal to distinguish similarly-worded
metrics from each other. This mirrors how a real semantic layer author
documents known query patterns; it isn't a retrieval-only hack bolted on
separately.

## Retrieval pipeline

```
question -> rewrite_query -> hybrid_search (k=8) -> rerank (k=4) -> context
```

- **`src/retrieval/indexer.py`** renders each table doc and metric into a
  flat text chunk (11 documents total at present) and builds two indices
  over them: a BM25 keyword index (`rank-bm25`) and a dense vector index
  (`sentence-transformers`, `all-MiniLM-L6-v2`, run locally, no API
  cost). Both are persisted to `data/indices/` and rebuilt by
  `scripts/seed_and_index.py`.
- **`src/retrieval/retriever.py`**'s `hybrid_search` combines normalized
  BM25 and cosine scores, weighted by `alpha` (production default 0.5,
  equal weight). Keyword and vector search are also exposed independently
  because the retrieval evaluation needs to compare all three (plus
  hybrid+rerank) against each other, not just ship the winner.
- **`src/retrieval/reranker.py`** scores each `(query, document)` pair
  *jointly* with a cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`,
  local), which is slower but far more precise than scoring query and
  document independently. It's deliberately a second pass over
  `hybrid_search`'s small candidate set (8 -> 4), not an independent
  first-pass retrieval method.
- **`src/retrieval/rewriter.py`**'s `rewrite_query` calls a local Ollama
  model to expand abbreviations and surface the business concepts a
  question is really asking about (e.g. "rev by region last qtr" ->
  mentions of revenue, region, time filtering) before retrieval runs. It
  falls back to the original question unchanged if the backend is
  unreachable: rewriting is an optimization on top of retrieval, not a
  hard dependency the pipeline can't function without.

**Measured, not assumed**: `evaluation/results/retrieval_eval.md` compares
all four approaches (keyword, vector, hybrid, hybrid+rerank) on hit rate
and MRR against the 50-question golden set, and documents a real
methodology story: the first version of hybrid+rerank actually scored
*worst*, traced to a specific, fixable cause (see the README's Evaluation
section for the summary). This is the evaluation that decided
`search_schema`'s production defaults, not the other way around.

## Agent loop

`src/agent/tools.py` exposes three composable functions rather than a
generic "tool-calling" abstraction, since the pipeline is fixed and linear
(retrieve, generate, execute, validate), not something the model itself
chooses a path through:

- **`search_schema(question, retriever, reranker)`** composes rewrite,
  hybrid search, and rerank into one call, returning the top-4 chunks as
  plain dicts (`{doc_id, type, name, text, score}`).
- **`run_sql(con, sql)`** is a thin wrapper over
  `guardrails.run_guarded_query`, kept as its own function so the agent
  loop's call sites read as "retrieve, generate, run, validate" without
  the guardrail mechanics inline.
- **`validate_result(question, result)`** is a heuristic, not an LLM call:
  reject empty or all-NULL results, and, because every rate/share metric
  in `metrics.yml` is defined as a fraction in `[0, 1]`, reject a numeric
  result outside that range when the question asks for a "rate",
  "percentage", "share", or "fraction". This is deliberately cheap and
  fast, but it is a plausibility check, not a correctness oracle: it
  cannot detect a wrong-but-plausible dimension, a silently-empty false
  answer from a casing mismatch, or a correct aggregation with the wrong
  label column. All three are real, traced failure modes in
  `evaluation/results/error_analysis.md`, disclosed as a limitation of
  this design rather than hidden.

`src/agent/loop.py`'s `answer_question` drives the retry loop: retrieve
once, then generate, execute, and validate up to `MAX_ATTEMPTS = 2`
times, feeding the previous attempt's error (guardrail violation, DuckDB
error, or `validate_result`'s rejection reason) back into the next
generation call as context. Context is retrieved once per question, not
re-retrieved per attempt: a failed attempt usually means the SQL was
wrong given the right context, not that retrieval itself needs to run
again. `generate_sql` accepts a `chat_fn` parameter (default: the local
Ollama `chat`, resolved at call time so tests can monkeypatch it) so
evaluation scripts can drive the *exact same* retry-loop logic against a
different backend (e.g. OpenAI) without duplicating the retry mechanics.
The loop itself is what gets measured, not a re-implementation of it.

**Measured, not assumed**: `evaluation/results/self_correction_eval.md`
measures the accuracy delta from enabling this retry loop (+0.020 on the
golden set) and reports the retry-triggered/rescued/regressed breakdown
explicitly, because `validate_result` being heuristic (not an oracle)
bounds how much lift retry can produce by construction: a confidently
wrong-but-plausible first attempt never gets a second try.

## Guardrail design

Kept in `src/agent/guardrails.py`, deliberately separate from
`tools.py`, so the safety logic is auditable in one small file rather
than interleaved with orchestration logic. Four independent layers, each
of which would stop a bad query on its own even if the others were
bypassed:

1. **Read-only connection** (`src/db/duckdb_client.py`): DuckDB itself
   refuses any write against a connection opened with `read_only=True`,
   independent of anything checked in Python above it. This was verified
   directly (not just asserted) by attempting writes against a read-only
   connection with the statement-level checks bypassed entirely.
2. **`check_select_only`**: rejects anything that isn't a single,
   standalone `SELECT`/`WITH ... SELECT` statement (no semicolon
   stacking), and independently rejects a keyword blocklist (`INSERT`,
   `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `ATTACH`, `PRAGMA`,
   `INSTALL`, ...) as a second, structurally different check, so a
   clever way to smuggle a write past the "starts with SELECT" check
   still gets caught by the keyword check, and vice versa.
3. **`apply_row_limit`**: wraps every query as
   `SELECT * FROM (...) LIMIT max_rows + 1`. Requesting one row past the
   cap (rather than exactly the cap) lets the caller detect true
   truncation instead of guessing from a row count that happens to equal
   the limit.
4. **`run_guarded_query`**'s timeout: executes on a background thread and
   calls `con.interrupt()` if it exceeds `QUERY_TIMEOUT_SECONDS` (10s
   default). Calibrated empirically before writing tests: a full
   600k x 600k self-cross-join of `fact_orders` reliably takes ~21s, and a
   1.0s timeout interrupts it in ~1.0s with the connection confirmed
   still usable immediately afterward.

All four layers are directly tested in `tests/test_agent_guardrails.py`,
including a parametrised rejection test across 13 disallowed statement
shapes: not just "the happy path works," but "here are 13 specific ways
someone might try to get around this, and each one is rejected."

## Interface

FastAPI (`src/app/api.py`) wraps `answer_question` as `POST /ask`,
`POST /feedback`, and `GET /health`. The chat backend is selected by
`AGENT_CHAT_BACKEND` (`ollama` default, `openai` opt-in) via
`_build_chat_fn`, which builds a fresh `chat_fn` and a fresh
`usage_records` list *per request* rather than sharing state across
calls; otherwise concurrent requests could mix each other's token usage
counts in the logged trace. Streamlit (`src/app/ui.py`) calls this API
over `httpx` rather than importing the agent loop directly, so the
interface and the agent stay independently deployable/scalable, and
`src/app/chart.py`'s `pick_chart_kind` is pure (no Streamlit import) so
its form-selection logic is unit-testable without running the app.

## Telemetry and monitoring

Every `/ask` and `/feedback` call appends a JSON line to
`data/telemetry/traces.jsonl` (`src/telemetry/logger.py`): a plain
append-only file, not a direct database write, specifically so the live
request path never depends on holding a write connection anywhere (the
warehouse connection is read-only, and a second writer connection would
be one more thing to keep alive correctly). `src/telemetry/dlt_pipeline.py`
is what turns this log into queryable DuckDB tables (`traces`,
`feedback`), loaded into a **separate** `data/telemetry.duckdb` file, not
the warehouse file, since the API holds a persistent read-only connection
to the warehouse for its whole lifetime, and DuckDB allows only one
read-write connection to a file at a time. `write_disposition="merge"` on
`query_id` makes reruns idempotent, so the pipeline can simply re-read the
whole log file every run rather than tracking an incremental offset
itself. `monitoring/dashboard.py` reads `telemetry.duckdb` and renders the
six required charts (queries over time, execution accuracy over time,
cost per query, latency p50/p95, feedback rate, top failure categories),
using pure data-prep functions in `monitoring/metrics.py`
(`compute_cost_usd`, `compute_percentiles`, `categorize_error`) kept
Streamlit-free for the same testability reason as `chart.py`.

## Orchestration

`orchestration/kestra/refresh_flow.yml` runs two sequential tasks: reseed
the warehouse and rebuild the retrieval indices
(`scripts/seed_and_index.py`), then reload telemetry
(`src/telemetry/dlt_pipeline.py`), nightly at 02:00, both inside the
project's own Docker image via Kestra's Docker task runner, both sharing
the same `warehouse_data` named volume the `api`/`ui`/`monitoring`
services read from. This means a refresh is visible to the running app
without a restart, verified directly, not assumed: a fresh question asked
immediately after a live-triggered flow run answered correctly against
the just-refreshed data, with no service restarted in between.

## What's deliberately not here

- **No write path anywhere in the agent's execution flow.** Not "writes
  are discouraged"; writes are structurally impossible at the connection
  level regardless of what SQL is generated.
- **No generic tool-calling framework.** The pipeline is a fixed sequence
  (retrieve, generate, execute, validate, maybe retry), not an open-ended
  agent choosing between arbitrary tools. A fixed pipeline is easier to
  guard, test, and reason about than a general one for this problem
  shape, and nothing in the project's scope needs the generality.
- **No LLM-based result validation.** `validate_result` is a cheap
  heuristic specifically so validation never becomes another thing that
  can hallucinate. Its limitations are documented above and in
  `evaluation/results/error_analysis.md` rather than papered over with a
  second model call that would have its own failure modes.
