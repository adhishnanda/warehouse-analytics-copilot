# Warehouse Analytics Copilot

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-305%20passing-brightgreen.svg)](docs/setup.md#running-the-tests)

Agentic text-to-SQL over a governed semantic layer. Ask a business
question in plain English and get back a number, the SQL that produced
it, and a chart, grounded in documented table and metric definitions
rather than a raw, ungoverned schema dump.

This is the capstone project for DataTalks.Club's **LLM Zoomcamp**. It is a
portfolio project, not a production system. See [Limitations](#limitations).

## Contents

- [Problem](#problem)
- [How it works](#how-it-works)
- [Dataset](#dataset)
- [Semantic layer](#semantic-layer)
- [Evaluation](#evaluation)
- [Interface](#interface)
- [Ingestion pipeline](#ingestion-pipeline)
- [Monitoring](#monitoring)
- [Guardrails](#guardrails)
- [Setup](#setup)
- [Deployment](#deployment)
- [Usage](#usage)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Limitations](#limitations)
- [License](#license)

## Problem

Handing an LLM a raw database schema and asking it to write SQL runs into
a predictable failure mode: the model finds the right *table* but guesses
the wrong *business logic*.

On this project's own warehouse, for example, `fact_orders` is stored at
line-item grain, not order grain. A naive "average order value" query
averages over line items and silently under-reports the real figure by
roughly 4x (TPC-H orders average ~4 lines each).

Real semantic layers (dbt Semantic Layer, LookML) solve this by defining
metrics once, centrally, as documented, named SQL, so "average order
value" always means the same formula everywhere it's used. An LLM
interface can be pointed at that definition instead of reinventing it
per question.

That's what "governed" means here: the agent never sees the full database
schema. It only sees the slice of table and metric documentation that a
retrieval step surfaces for the specific question asked, from a small,
hand-curated `semantic_layer/` knowledge base (YAML table docs plus named
metric SQL). This turns "does retrieval help" from an assumption into
something measured directly. See the
[Tier-3 ablation](evaluation/results/ablation_eval.md), which shows this
mechanism catching exactly the grain mistake described above.

## How it works

1. User asks a question via the web app
2. Query rewriting expands it into a retrieval-friendlier form (local
   Ollama model, falls back to the original question if unreachable)
3. Hybrid search (BM25 + vector) retrieves candidate chunks from the
   semantic layer, then a cross-encoder reranks them
4. The agent generates SQL, grounded only in the retrieved context
5. SQL runs against a read-only DuckDB connection, under guardrails
   (SELECT-only, row limit, query timeout)
6. The result is validated by a plausibility heuristic; on failure, the
   agent retries with the error fed back (up to 2 attempts total)
7. The answer, the SQL, and a chart are returned; the exchange is logged

```
question -> rewrite -> hybrid search -> rerank -> generate SQL -> guarded execute
                                                        ^                |
                                                        |                v
                                                   retry (<=2)  <-  validate result
```

Full design rationale (why DuckDB, why this semantic layer format, the
guardrail layering, retrieval/agent internals) is in
[`docs/architecture.md`](docs/architecture.md).

## Dataset

**TPC-H**, generated via DuckDB's built-in `dbgen` at scale factor 0.1. It
is not downloaded from anywhere, so the exact same data is reproducible
from a clean clone with no external dependency or licensing question. It
is *not* the LLM Zoomcamp course FAQ dataset (which is disallowed by the
course rules). `data/seed_warehouse.py` reshapes TPC-H's native tables
into a 6-table star schema:

| Table | Grain | Rows (scale factor 0.1) |
|---|---|---|
| `fact_orders` | one row per order line | 600,572 |
| `dim_customer` | one row per customer | 15,000 |
| `dim_supplier` | one row per supplier | 1,000 |
| `dim_product` | one row per product | 20,000 |
| `dim_date` | one row per calendar day | 2,553 |
| `dim_region` | one row per nation | 25 |

`dim_region` is nation-grain (TPC-H's own `region` table is only 5 rows,
too coarse to be a useful independent join target); region is carried as
an attribute on each nation. TPC-H's `dbgen` is deterministic at a fixed
scale factor, verified independently by reseeding twice and comparing row
counts and aggregates, which is what makes it possible to bake real
reference results into the golden evaluation set rather than compute them
fresh at evaluation time.

## Semantic layer

`semantic_layer/` is the knowledge base the agent retrieves from. It sits
at the repo root, not under `src/`, because it *is* the point of the
project, not an implementation detail. It has two parts:

- `semantic_layer/tables/*.yml`: one file per table, with description,
  grain, every column's type and meaning, join keys, and caveats (e.g.
  `fact_orders.yml` states explicitly that it's line-item grain, and that
  counting rows answers "how many order lines", not "how many orders")
- `semantic_layer/metrics.yml`: named business metrics, each with a prose
  description and the exact backing SQL, so the agent uses one canonical
  formula rather than inventing its own per question:

```yaml
average_order_value:
  description: >
    Total net revenue divided by the number of distinct orders. Answers
    "how much does a typical order bring in", not "how much does a typical
    order line bring in".
  sql: |
    SELECT SUM(net_revenue) * 1.0 / COUNT(DISTINCT order_key) AS average_order_value
    FROM fact_orders
```

Every documented column is tested against the live warehouse's actual
`PRAGMA table_info` in both directions, so the YAML cannot silently drift
from the real schema (`tests/test_semantic_layer.py`).

## Evaluation

All results below are measured against the 50-question golden set
(`evaluation/golden_questions.jsonl`: 20 Tier-1 single-table aggregations,
20 Tier-2 joins/time filters, 10 Tier-3 metric-definition questions), with
every gold reference result executed against the real warehouse, not
hand-computed. Full methodology, by-tier breakdowns, and raw numbers for
every table below are in `evaluation/results/`.

### Retrieval evaluation

Hit rate / MRR @ k=5, keyword-only vs vector-only vs hybrid vs hybrid +
rerank ([`evaluation/results/retrieval_eval.md`](evaluation/results/retrieval_eval.md)):

| Approach | Hit rate | MRR |
|---|---|---|
| Keyword only | 0.980 | 0.697 |
| Vector only | 0.960 | 0.751 |
| Hybrid | 1.000 | 0.741 |
| Hybrid + rerank | 1.000 | 0.758 |

Best approach used in production: **Hybrid + rerank**

The first run of this evaluation actually found keyword-only winning, with
hybrid + rerank scoring lowest. The full report documents the diagnosis
(the reranker had too little signal to distinguish short, formulaic metric
chunks), the fix (adding representative example phrasings to each metric),
and a genuine trade-off the fix exposed: it measurably *degraded*
keyword-only search while hybrid stayed robust, real evidence for hybrid
being the more robust default, not an assumed one.

### LLM evaluation

Execution accuracy (generated SQL executed under guardrails, compared to
the golden reference as an order-insensitive row set), 2 models x 2
prompts ([`evaluation/results/llm_eval.md`](evaluation/results/llm_eval.md)):

| Model | Prompt | Execution accuracy |
|---|---|---|
| `llama3` (local, free) | baseline (raw schema dump) | 0.340 |
| `llama3` (local, free) | schema-grounded | 0.600 |
| `gpt-4o-mini` (paid) | baseline (raw schema dump) | 0.620 |
| `gpt-4o-mini` (paid) | schema-grounded | 0.880 |

Best approach used in production: **`gpt-4o-mini` / schema-grounded**

The free-tier arm was originally Groq's hosted `llama-3.3-70b-versatile`.
It was dropped after its free daily quota was exhausted mid-evaluation
(full incident writeup in the report) in favour of local Ollama, which has
no external rate limit to fight.

### Self-correction lift

Validate-and-retry loop (max 2 attempts) vs single-shot, `gpt-4o-mini` +
schema-grounded context, same 50 questions
([`evaluation/results/self_correction_eval.md`](evaluation/results/self_correction_eval.md)):

| Condition | Execution accuracy |
|---|---|
| Single-shot (no retry) | 0.840 |
| Retry-enabled (max 2 attempts) | 0.860 |

Accuracy delta: **+0.020**. Retry was triggered on 4 of 50 questions (1
rescued, 0 regressed). `validate_result` is a plausibility heuristic, not
a correctness oracle, so it bounds how much lift a retry loop can produce
by construction: an attempt that's confidently wrong in a way the
heuristic can't detect never gets a second try.

### Tier-3 retrieval ablation (headline result)

The 10 Tier-3 questions (only answerable correctly via a defined metric),
run with the semantic layer retrieval disabled (raw schema dump only) vs
enabled, 2 models
([`evaluation/results/ablation_eval.md`](evaluation/results/ablation_eval.md)):

| Model | Retrieval disabled | Retrieval enabled |
|---|---|---|
| `llama3` (local, free) | 0.300 | 0.800 |
| `gpt-4o-mini` (paid) | 0.500 | 1.000 |

This is the project's central, most distinctive result: it demonstrates,
with measured numbers on both a free and a paid model, that
retrieval-grounded generation improves accuracy specifically where
business metric definitions matter, not a generic "RAG helps" claim.
[`evaluation/results/error_analysis.md`](evaluation/results/error_analysis.md)
traces the concrete mechanism: without retrieval, `gpt-4o-mini` reinvents
`average_order_value` as `AVG(net_revenue)` over line items (wrong grain)
on every sampled attempt; with retrieval, it uses the documented formula
and scores 1.000 on all 10 Tier-3 questions.

### Known limitations, measured not assumed

`evaluation/results/error_analysis.md` documents seven distinct failure
categories found by tracing real generated SQL, including cases the
guardrails and validation heuristic cannot catch: a wrong-but-plausible
dimension choice, a stored-value casing mismatch that silently returns a
false zero-row answer, and a retry that repeats an identical mistake even
though the database's own error message named the fix. These are treated
as disclosed, measured limitations, not hidden.

## Interface

FastAPI backend (`src/app/api.py`: `POST /ask`, `POST /feedback`,
`GET /monitoring/*`) that also serves a React single-page app
(`frontend/`, TypeScript + Tailwind + shadcn/ui + Recharts) as one process
on one port. A sidebar splits it into two views:

- **Ask**: chat-style UI, answer rendered as a stat tile, KPI row, chart,
  or table depending on shape, SQL shown in a disclosure, thumbs up/down
  feedback
- **Monitoring**: the dashboard described below

Chart type selection (`src/app/chart.py`'s `pick_chart_kind`) runs
server-side and is returned in the `/ask` response, so the same
tested logic drives the UI without being duplicated in TypeScript.

## Ingestion pipeline

Two Kestra flows, both running sequential tasks in Docker containers built
from this project's own image, sharing the same data volume the running
app reads from, so a refresh is visible without a restart:

- `orchestration/kestra/refresh_flow.yml`: reseeds the warehouse and
  rebuilds the retrieval indices, then loads new telemetry, nightly at
  02:00.
- `orchestration/kestra/synthetic_traffic_flow.yml`: runs a batch of
  synthetic traffic (`scripts/generate_synthetic_traffic.py`) through the
  real agent loop, then reloads telemetry the same way, daily at 06:00 -
  see Monitoring below for why this exists.

[Kestra](https://kestra.io) is an open-source workflow orchestrator.

## Monitoring

The Monitoring page (`frontend/src/components/monitoring/`) with 6 named
charts, reading from JSON endpoints (`src/app/monitoring.py`) backed by a
[dlt](https://dlthub.com) pipeline (`src/telemetry/dlt_pipeline.py`) that
loads the raw per-request trace log into DuckDB tables:

1. Queries over time
2. Execution accuracy over time
3. Cost per query
4. Latency (p50/p95)
5. Feedback rate (thumbs up/down)
6. Top failure categories

User feedback is collected via thumbs up/down in the UI, logged through
the same trace pipeline. Demo telemetry used to originally exercise the
dashboard (20 traces: 12 free `llama3` and 5 paid `gpt-4o-mini` scripted
questions, plus 3 organic ones from manual testing) is demo-run data, not
a formal evaluation result; the Evaluation section above is the source
for accuracy and retrieval claims. The daily synthetic-traffic flow above
adds roughly a dozen more real traces (plus simulated feedback) each day,
using the same production agent loop and the free local Ollama backend,
so the dashboard keeps showing activity between real sessions rather
than sitting static.

## Guardrails

Four independent layers, kept in one small auditable file
(`src/agent/guardrails.py`), because LLM-generated SQL should never be
trusted with implicit permissions:

1. **Read-only connection** (`src/db/duckdb_client.py`): DuckDB itself
   refuses any write, independent of anything checked above it
2. **SELECT-only whitelist** (`check_select_only`): rejects anything that
   isn't a single standalone `SELECT`/`WITH ... SELECT`, and separately
   rejects a keyword blocklist (`INSERT`, `DROP`, `ATTACH`, `PRAGMA`, ...)
3. **Row limit** (`apply_row_limit`): every query is wrapped so at most
   1,000 rows can ever be returned
4. **Query timeout** (`run_guarded_query`): a watchdog thread interrupts
   the connection if execution exceeds 10 seconds

All four layers are directly tested, including a parametrised rejection
test across 13 disallowed statement shapes and an empirical timeout test
(a real 600k x 600k self-join, confirmed to interrupt on schedule with the
connection still usable afterward). See `tests/test_agent_guardrails.py`.

## Setup

Full step-by-step instructions (prerequisites, environment variables,
Docker and non-Docker paths, how to verify each service, how to reproduce
the evaluation numbers above) are in
[`docs/setup.md`](docs/setup.md). Quick start:

```bash
git clone <repo-url>
cd warehouse-analytics-copilot
cp .env.example .env
docker compose up --build
```

Then open `http://localhost:8000`: the Ask page and Monitoring page are
both served from that one address (`/ask` and `/monitoring`), by the same
FastAPI process as the API itself (`/health`, `/ask`, `/monitoring/*`). By
default the API answers questions using the free local model. See
`docs/setup.md` for the Ollama prerequisite and how to opt into the paid
backend instead.

Dependency versions are pinned throughout: `uv.lock` (committed) for every
Python package, `python:3.13.7-slim-bookworm` plus `uv==0.11.20` in the
`Dockerfile`, `kestra/kestra:v1.3.30` and `postgres:15.18` in
`docker-compose.yml`.

## Deployment

`render.yaml` deploys this repo's own `Dockerfile` as a single public web
service on [Render](https://render.com)'s free tier, the optional cloud
deployment item from the LLM Zoomcamp rubric (see
[`PROJECT_PLAN.md`](PROJECT_PLAN.md) Section 3). Local Ollama isn't
realistically deployable on a typical free-tier host, so the public
instance runs on `gpt-4o-mini` instead, bounded by a daily query cap
(`MAX_DAILY_QUERIES`, default 50) so an anonymous visitor can't run up an
open-ended bill. Kestra orchestration stays local-only - its Docker task
runner needs a Docker socket a PaaS container doesn't provide - and the
free tier's filesystem is ephemeral, so the Monitoring page's telemetry
resets on every restart rather than accumulating indefinitely. Both
tradeoffs are deliberate scope decisions for a portfolio demo, not
oversights. Full steps: [`docs/setup.md`](docs/setup.md#deploying-to-render).

## Usage

Example questions, what each answer shape looks like, and how to read the
monitoring dashboard: [`docs/usage.md`](docs/usage.md).

## Architecture

Full design write-up covering why DuckDB, why this semantic layer format,
retrieval and agent internals, the guardrail design, telemetry, and
orchestration: [`docs/architecture.md`](docs/architecture.md).

## Tech stack

| Layer | Tool |
|---|---|
| Knowledge base / warehouse | DuckDB + YAML semantic layer |
| Retrieval | `rank-bm25` (keyword), `sentence-transformers` `all-MiniLM-L6-v2` (vector), `cross-encoder/ms-marco-MiniLM-L-6-v2` (rerank); all local, no API cost |
| LLM | Local Ollama (`llama3`) for development and the free evaluation arm; OpenAI `gpt-4o-mini` for the paid evaluation arm and the production default in the shipped system |
| Agent orchestration | Function-calling-style tool composition plus a custom retry loop (`src/agent/`) |
| Interface | FastAPI (backend, and serves the built frontend as static assets) + React/TypeScript/Vite, Tailwind, shadcn/ui, Recharts (frontend) |
| Ingestion / orchestration | Kestra (nightly refresh + daily synthetic-traffic flows), dlt (telemetry ingestion) |
| Monitoring | React dashboard, 6 charts, reading JSON from `/monitoring/*` (backed by dlt-loaded DuckDB tables) |
| Containerization | Single `docker-compose.yml` (4 services, 1 shared image built via a multi-stage Dockerfile, 1 shared data volume) |
| Testing | pytest, 305 tests (backend); `npm run build` type-checks the frontend |

## Limitations

- **Schema scope is deliberately small** (1 fact and 5 dimension tables).
  This is a stated design choice, not an apology, but it means these
  accuracy numbers do not claim to generalise to a sprawling, real-world
  warehouse.
- **`validate_result` is a plausibility heuristic, not a correctness
  oracle.** It catches empty/NULL results and out-of-range rate values,
  but not a wrong-but-plausible dimension choice, a silently-empty false
  answer from a stored-value casing mismatch, or a technically-correct
  aggregation with a mislabelled grouping column (real examples of all
  three are in `evaluation/results/error_analysis.md`).
- **Retry does not reliably correct a wrong mental model of the schema.**
  One traced case fed the model DuckDB's own error message, which named
  the correct column in its candidate-bindings list, and the retry
  repeated the identical mistake anyway.
- **Execution-accuracy-by-exact-match cannot distinguish "logically
  correct, wrong label column" from "logically wrong."** A query that
  grouped by `nation_key` instead of `nation_name` produced revenue
  figures that matched the golden reference exactly once mapped back to
  names, but was scored as fully incorrect by the exact-match methodology
  used throughout, disclosed as an evaluation-methodology caveat, not
  only a model one.
- **The LLM API is not called at a pinned temperature**, so evaluation
  numbers are single measured samples of a non-deterministic model, not
  guaranteed to reproduce exactly on a rerun. See the variance note in
  `evaluation/results/self_correction_eval.md`.
- **This is a portfolio project, not a production system.** Guardrails,
  monitoring, and evaluation exist and are real, but it has not been load
  tested, has no auth on the API, and has not been exposed publicly.

## License

MIT. See [`LICENSE`](LICENSE).
