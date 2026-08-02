# Warehouse Analytics Copilot — Full Project Plan

**LLM Zoomcamp capstone project**
**Owner:** Adhish Nanda
**Status:** Planning complete, build not yet started

---

## 1. What we are trying to do

We are building an **agentic text-to-SQL system grounded in a governed semantic
layer**. In plain terms: a user asks a business question in English ("what was
repeat-purchase revenue by region last quarter?"), and the system retrieves the
relevant table and metric documentation, writes SQL against a small analytics
warehouse, runs it safely, checks the result, and answers with the number, the
SQL that produced it, and a chart.

This is the capstone project for the DataTalks.Club **LLM Zoomcamp** course.
It satisfies the course requirement to build an end-to-end RAG or agent
application, and it is designed from the ground up against the course's
official evaluation rubric (see Section 3).

### 1.1 Why this project, specifically

Three reasons this was chosen over other LLM Zoomcamp project ideas:

1. **It matches the target job market.** The primary job targets are
   Analytics Engineer, Data Analyst / BI Analyst, and Junior Data Engineer
   roles in Germany. "LLM interface over a governed semantic layer" is a
   pattern actively being explored by German companies working with dbt/BI
   stacks — it speaks to analytics roles, not just AI/ML roles.
2. **It differs structurally from prior work.** The MSc thesis is a
   document-RAG system (BM25/FAISS retrieval, reranking, RAGAS evaluation
   over text documents). A second document-RAG project would look like a
   smaller copy of the thesis to any reviewer or recruiter. This project
   retrieves **schema and metric metadata**, not documents, and evaluates
   **SQL execution correctness**, not text-answer quality — a genuinely
   different technical problem that still reuses skills the thesis already
   demonstrates competence in (retrieval, evaluation rigour).
3. **It extends existing project history coherently.** The `ecommerce-dbt-stack`
   project already shows the ability to build a governed Kimball warehouse.
   This project puts a safe, evaluated LLM interface on top of that pattern.
   Interview narrative: warehouse → copilot → thesis-level evaluation rigour,
   three projects, one coherent professional identity.

### 1.2 What "governed" means here

The semantic layer is not a convenience feature — it is the point of the
project. Instead of handing an LLM the full database schema and hoping it
writes correct SQL, the system:

- Documents every table and column in plain YAML, with descriptions and caveats
- Defines business metrics explicitly (e.g. "repeat purchase rate") as named,
  documented SQL, not left to the LLM to invent
- Retrieves only the relevant slice of this documentation per question
- Restricts the LLM to a read-only, guarded SQL execution path

This mirrors how real semantic layers work (dbt Semantic Layer, LookML), which
is exactly the vocabulary Analytics Engineer interviewers use.

---

## 2. Constraints and ground rules

These apply throughout the build, not just at the end:

- **No fabricated metrics.** Every number reported in the README, evaluation
  tables, or CV bullets must come from an actual measured run. If a metric
  hasn't been measured yet, it stays blank or marked "pending" — never
  estimated or invented.
- **Cost ceiling: roughly €0–5 total**, using free-tier inference (Groq,
  Ollama) for development and a small paid model only for final,
  reproducible evaluation runs.
- **Buildable with Claude Code / ChatGPT at a basic tier.** No tooling that
  requires paid infrastructure beyond what's listed in Section 6.
- **Timebox: 3 weeks**, structured so that if time is lost, the cuts happen
  in a defined order (see Section 8, "if time runs short").
- **Never described as "production."** It is production-*patterned* —
  guardrails, monitoring, and evaluation exist, but this is a portfolio
  project, not a live commercial system. Positioned under "Projects," not
  "Professional Experience."
- **Dataset must not be the DTC course FAQ corpus** (explicitly disallowed
  by the course rules). TPC-H (DuckDB's built-in generator) or the UK Online
  Retail dataset are the two candidates; both are external and permitted.

---

## 3. Alignment with the official LLM Zoomcamp evaluation rubric

Every design decision below is traceable back to a specific rubric line.
This section is the scoring plan.

| Criterion | Max points | How this project earns it |
|---|---|---|
| Problem description | 2 | Clearly written README problem statement, for readers who did not take the course |
| Retrieval flow | 2 | Semantic layer (knowledge base) + LLM used together in the agent loop |
| Retrieval evaluation | 2 | Named comparison: keyword-only vs vector-only vs hybrid vs hybrid+rerank, with a stated winner |
| LLM evaluation | 2 | Named comparison: 2 models × 2 prompts, with a stated winner |
| Interface | 2 | FastAPI backend + Streamlit UI |
| Ingestion pipeline | 2 | Automated: Kestra nightly refresh flow, dlt for telemetry ingestion |
| Monitoring | 2 | User feedback (thumbs up/down) collected + dashboard with 6 named charts (rubric requires 5+) |
| Containerization | 2 | Single `docker-compose.yml` bringing up the full stack, not just a Dockerfile |
| Reproducibility | 2 | Clear setup instructions, accessible dataset, pinned dependency versions |
| **Best practices (3 items, 1 pt each)** | 3 | Hybrid search (evaluated), document reranking, query rewriting — all three implemented |
| **Bonus: cloud deployment** | +2 | Stretch goal only, attempted if Week 3 finishes early |
| **Core total** | **21/24** | before bonus |

This scoring table is the reason the build plan below includes reranking and
query rewriting, and a single consolidated `docker-compose.yml` — these are
not optional extras, they are the difference between a passing project and a
near-maximum one, for roughly 4–5 hours of additional work.

---

## 4. Dataset and schema

**Candidate datasets:** DuckDB's built-in TPC-H generator (`CALL dbgen(sf=0.1)`)
or the UK Online Retail dataset. Either works; the decision should be made in
Week 1, Day 1, based on which produces a cleaner, smaller star schema.

**Schema scope, deliberately small:** one fact table (orders or line items)
and 5–6 dimension tables (customer, product, date, region, supplier). This is
a deliberate constraint, not a limitation to apologise for — a 6–8 table
schema is the difference between plausibly reporting 80%+ execution accuracy
and reporting 40% on a sprawling one. It is framed in the README as "governed
scope," consistent with how real semantic layers are scoped in practice.

---

## 5. System architecture

### 5.1 Pipeline

1. **User asks a question** in plain English via the Streamlit UI
2. **Query rewriting** expands the question into a retrieval-friendlier form
   (expands abbreviations, surfaces likely table/metric names)
3. **Hybrid retrieval** (keyword + vector search) pulls candidate chunks from
   the semantic layer (table docs, metric definitions)
4. **Reranking** (cross-encoder) re-orders retrieved chunks by relevance
5. **Agent generates SQL**, grounded only in the retrieved, reranked context
6. **SQL executes** against a read-only, guarded DuckDB connection
7. **Result is validated**; on failure or empty result, the agent retries
   (maximum 2 attempts)
8. **Answer returned**: the number, the SQL used, and a chart
9. **Every exchange is logged** as a trace, feeding the monitoring layer

### 5.2 Semantic layer (the knowledge base)

One YAML file per table (`semantic_layer/tables/*.yml`) containing:
description, column meanings, join keys, known caveats. Plus a single
`semantic_layer/metrics.yml` defining business metrics in both prose and SQL,
e.g.:

```yaml
repeat_purchase_rate:
  description: "Share of customers with 2 or more orders"
  sql: |
    SELECT COUNT(DISTINCT CASE WHEN order_count >= 2 THEN customer_id END)
           * 1.0 / COUNT(DISTINCT customer_id)
    FROM customer_order_counts
```

The agent never sees the full schema at once — it only sees what retrieval
surfaces for a given question. This is what makes "retrieval evaluation" a
real, meaningful axis to measure (Section 3).

### 5.3 Agent tools

Three tools exposed via function calling:

- `search_schema(question)` — runs the retrieval + rerank pipeline
- `run_sql(query)` — executes SQL through the guarded connection
- `validate_result(question, result)` — checks whether the result plausibly
  answers the question; triggers retry if not

### 5.4 Guardrails (kept in a separate, auditable file)

- Read-only DuckDB connection — no write access at all
- SQL statement whitelist: `SELECT` only
- Row limit on all queries
- Query timeout
- Maximum 2 retry attempts, all attempts logged

These live in `src/agent/guardrails.py`, deliberately separated from
`tools.py` so a reviewer — or an interviewer — can audit the safety logic in
one small, self-contained file.

### 5.5 Models

- **Development:** Groq free tier (Llama 3.3 70B) and/or local Ollama —
  zero or near-zero cost
- **Final evaluation runs:** one small paid model (e.g. GPT-4o-mini or
  Claude Haiku) so the reported numbers come from a named, reproducible
  model — total cost expected in the low single-digit euros

---

## 6. Tech stack

| Layer | Tool |
|---|---|
| Knowledge base / warehouse | DuckDB + YAML semantic layer |
| Retrieval | Hybrid search (keyword + vector), cross-encoder reranking |
| LLM | Groq (Llama 3.3 70B) / Ollama for dev; one paid model for eval |
| Agent orchestration | Function calling, custom retry loop |
| Interface | FastAPI (backend) + Streamlit (frontend) |
| Ingestion / orchestration | Kestra (nightly refresh), dlt (telemetry ingestion) |
| Monitoring | Streamlit dashboard, 6 charts |
| Containerization | Single `docker-compose.yml` |
| Testing | pytest |

---

## 7. Evaluation design

### 7.1 Golden question set

50 hand-written question–SQL pairs, split into three tiers:

- **Tier 1 (~20 questions):** single-table aggregations
- **Tier 2 (~20 questions):** joins and time filters (e.g. "revenue by
  region last quarter")
- **Tier 3 (~10 questions):** metric-definition questions that only succeed
  if retrieval finds the correct metric YAML (e.g. "what's our repeat
  purchase rate trend")

Tier 3 exists specifically to prove the semantic layer matters — see the
ablation below.

### 7.2 Retrieval evaluation

Compare, on the golden set: keyword-only vs vector-only vs hybrid vs
hybrid+rerank. Report hit rate and MRR for each. State the winner and use it
in the shipped system.

### 7.3 LLM evaluation

Compare 2 models × 2 prompt strategies (baseline prompt vs schema-grounded
prompt). Report execution accuracy for each combination. State the winner
and use it in the shipped system.

### 7.4 Self-correction lift

Measure execution accuracy with the validate-and-retry loop enabled vs a
single-shot attempt (no retry). Report the accuracy delta.

### 7.5 Tier-3 ablation (headline result)

Run Tier-3 questions with the semantic layer retrieval disabled (LLM sees
only raw schema, no metric definitions) vs enabled. This is the project's
most distinctive result: it demonstrates, with real measured numbers, that
retrieval-grounded generation improves accuracy specifically where business
metric definitions matter — not just a generic "RAG helps" claim.

### 7.6 Metrics tracked in the monitoring dashboard

Execution accuracy, retrieval hit rate, hallucinated-column rate,
self-correction lift, cost per query, latency (p50/p95) — all over time,
not just as one-off eval numbers.

---

## 8. Three-week build schedule

### Week 1 — Core system

| Day | Task |
|---|---|
| 1 | Repo skeleton, docker-compose shell, dataset chosen and loaded into DuckDB star schema |
| 2 | YAML semantic layer: table docs + `metrics.yml` with business definitions |
| 3 | Baseline keyword retrieval, then add vector retrieval over metadata |
| 4 | **[rubric add-on]** Query rewriting step before retrieval |
| 5 | **[rubric add-on]** Cross-encoder reranking over retrieved chunks |
| 6–7 | Agent loop: `search_schema`, `run_sql`, `validate_result` tools; read-only SQL guard implemented and tested |

### Week 2 — Evaluation (this is where most rubric points are earned)

| Day | Task |
|---|---|
| 8–9 | Write 50 golden question–SQL pairs across 3 difficulty tiers |
| 10 | **[rubric]** Retrieval evaluation: keyword vs vector vs hybrid vs hybrid+rerank, table + stated winner |
| 11 | **[rubric]** LLM evaluation: 2 models × 2 prompts, table + stated winner |
| 12 | Self-correction retry loop; measure accuracy lift vs single-shot |
| 13–14 | Tier-3 retrieval ablation (headline result); write up error analysis |

### Week 3 — Production and submission

| Day | Task |
|---|---|
| 15–16 | Streamlit UI: answer, SQL, chart, thumbs up/down feedback |
| 17 | dlt pipeline: traces logged into DuckDB telemetry tables |
| 18 | **[rubric]** Monitoring dashboard with 6 named charts (rubric requires 5+) |
| 19 | Kestra nightly refresh flow |
| 20 | **[rubric]** Consolidate into a single `docker-compose.yml` (app + DB + Kestra), pin all dependency versions |
| 21 | Write the full README (see Section 10), run tests, submit |

### If time runs short — cut order

If a day is lost, cut in this order (top items are safest to cut, bottom
items should never be cut):

1. Cloud deployment bonus (never scheduled by default — see Section 3)
2. Model comparison — reduce to 1 model × 2 prompts instead of 2×2
3. Kestra orchestration — fall back to a documented manual/script refresh
   (drops ingestion pipeline to 1 point instead of 2)
4. **Never cut:** the golden question set, the retrieval/LLM evaluation
   tables, or the guardrails — these are the core of both the rubric score
   and the interview story

---

## 9. Repository structure

```
warehouse-analytics-copilot/
├── README.md
├── LICENSE
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore
├── requirements.txt
├── pyproject.toml
│
├── data/
│   ├── raw/                        # downloaded source data (gitignored)
│   ├── warehouse.duckdb            # gitignored — generated by seed script
│   └── seed_warehouse.py           # loads TPC-H/retail data, builds star schema
│
├── semantic_layer/
│   ├── tables/
│   │   ├── fact_orders.yml
│   │   ├── dim_customer.yml
│   │   ├── dim_product.yml
│   │   ├── dim_date.yml
│   │   ├── dim_region.yml
│   │   └── dim_supplier.yml
│   └── metrics.yml                 # business metric definitions + SQL
│
├── src/
│   ├── __init__.py
│   ├── config.py                   # env vars, model names, paths
│   │
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── indexer.py              # builds keyword + vector indices
│   │   ├── rewriter.py             # query rewriting step
│   │   ├── retriever.py            # hybrid search
│   │   └── reranker.py             # cross-encoder reranking
│   │
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── tools.py                # search_schema, run_sql, validate_result
│   │   ├── loop.py                 # agent orchestration + retry logic
│   │   └── guardrails.py           # read-only SQL check, row limits, timeout
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   └── duckdb_client.py        # sandboxed read-only connection
│   │
│   ├── telemetry/
│   │   ├── __init__.py
│   │   ├── logger.py               # writes traces per query
│   │   └── dlt_pipeline.py         # dlt pipeline: traces -> telemetry tables
│   │
│   └── app/
│       ├── __init__.py
│       ├── api.py                  # FastAPI backend
│       └── ui.py                   # Streamlit frontend
│
├── monitoring/
│   └── dashboard.py                # Streamlit dashboard, 6 charts
│
├── orchestration/
│   └── kestra/
│       └── refresh_flow.yml        # nightly data refresh DAG
│
├── evaluation/
│   ├── golden_questions.jsonl      # 50 question-SQL pairs, tiered
│   ├── run_retrieval_eval.py       # keyword vs vector vs hybrid vs hybrid+rerank
│   ├── run_llm_eval.py             # model x prompt comparison
│   ├── run_ablation.py             # tier-3 retrieval ablation
│   └── results/
│       ├── retrieval_eval.md
│       ├── llm_eval.md
│       └── error_analysis.md
│
├── tests/
│   ├── test_retrieval.py
│   ├── test_agent_guardrails.py
│   ├── test_tools.py
│   └── test_telemetry.py
│
├── scripts/
│   ├── setup.sh                    # one-command setup: data, indices, docker
│   └── seed_and_index.py
│
└── docs/
    ├── setup.md
    ├── usage.md
    ├── architecture.md
    └── screenshots/
```

**Design notes:**
- `semantic_layer/` sits at the repo root, not under `src/`, because it *is*
  the knowledge base — a reviewer should find it immediately.
- `evaluation/results/` holds committed markdown files with actual numbers,
  not just scripts, so a reviewer sees real results without running anything.
- `guardrails.py` is kept separate from `tools.py` specifically so the
  safety logic is auditable in one small file — useful both for review and
  for interview discussion.

---

## 10. README skeleton

This is the structure the final `README.md` should follow. Every
`<!-- comment -->` marks a section that must be filled with real,
measured content before submission — never left as a placeholder and never
filled with invented numbers.

```markdown
# Warehouse Analytics Copilot

Agentic text-to-SQL over a governed semantic layer. Ask a business
question in plain English; get back a number, the SQL that produced
it, and a chart — grounded in documented table and metric definitions
rather than a raw, ungoverned schema dump.

[screenshot: main UI]

## Problem
<!-- Written for someone who has not taken the course. What business -->
<!-- problem does naive text-to-SQL usually get wrong, and what does -->
<!-- "governed" mean here. 1-2 paragraphs. -->

## Demo
[screenshot or short video: asking a question, getting an answer]

## How it works
1. User asks a question
2. Query rewriting expands it into retrieval-friendly form
3. Hybrid search + reranking retrieve relevant table docs and metric definitions
4. Agent generates SQL, grounded in retrieved context
5. SQL runs against a read-only DuckDB connection, with guardrails
6. Result is validated; on failure, the agent retries (up to 2x)
7. Answer, SQL, and a chart are returned; the exchange is logged

[diagram: pipeline]

## Dataset
<!-- What data, where from, how it's licensed, why chosen. -->
<!-- Confirm it is NOT the DTC course FAQ dataset. -->

## Semantic layer
<!-- What's in semantic_layer/, why it exists, one example YAML snippet -->

## Evaluation

### Retrieval evaluation
| Approach | Hit rate | MRR |
|---|---|---|
| Keyword only | | |
| Vector only | | |
| Hybrid | | |
| Hybrid + rerank | | |

Best approach used in production: **[X]**

### LLM evaluation
| Model | Prompt | Execution accuracy |
|---|---|---|
| Model A | Baseline | |
| Model A | Schema-grounded | |
| Model B | Baseline | |
| Model B | Schema-grounded | |

Best approach used in production: **[X]**

### Self-correction and ablation
<!-- Retry lift. Tier-3 ablation: accuracy with vs without semantic layer retrieval. -->

Full results and error analysis: [`evaluation/results/`](evaluation/results/)

## Interface
FastAPI backend + Streamlit frontend.

## Ingestion pipeline
Kestra flow refreshes the warehouse nightly. <!-- explain what Kestra is -->

## Monitoring
Dashboard with:
1. Queries over time
2. Execution accuracy over time
3. Cost per query
4. Latency (p50/p95)
5. Feedback rate (thumbs up/down)
6. Top failure categories

User feedback collected via thumbs up/down, logged through the dlt
pipeline. <!-- explain what dlt is -->

[screenshot: dashboard]

## Guardrails
<!-- read-only connection, statement whitelist, row limits, timeout -->
<!-- why this matters for LLM-generated SQL -->

## Setup
See docs/setup.md for full instructions. Quick start:
\`\`\`bash
git clone <repo>
cd warehouse-analytics-copilot
cp .env.example .env   # add your API key
docker-compose up --build
\`\`\`
Dependency versions: see requirements.txt / pyproject.toml (all pinned).

## Usage
See docs/usage.md for example questions and walkthroughs.

## Architecture
See docs/architecture.md for the full design, including why DuckDB,
why this semantic layer format, and the guardrail design.

## Tech stack
- LLM: <!-- e.g. Groq (Llama 3.3 70B) for dev, [X] for eval runs -->
- Knowledge base: DuckDB + YAML semantic layer
- Retrieval: hybrid search, cross-encoder reranking
- Interface: FastAPI + Streamlit
- Ingestion: Kestra, dlt
- Monitoring: Streamlit dashboard

## Limitations
<!-- honest, specific: schema scope, accuracy on tier-3, what's out of scope -->

## License
MIT
```

---

## 11. Positioning rules for after the project is built

These carry forward into CV, LinkedIn, and interview prep once the project
is complete and real numbers exist:

- Lives under **Projects**, never under Professional Experience
- Never called "production" — describe it as production-*patterned*
  (guardrails, monitoring, evaluation present; portfolio scope)
- Every number used anywhere (CV, LinkedIn, interviews) must trace back to
  an actual measured run in `evaluation/results/`
- Interview narrative arc: `ecommerce-dbt-stack` (governed warehouse) →
  this project (safe LLM interface on top of one) → MSc thesis (rigorous
  LLM system evaluation) — three projects, one coherent identity
- CV bullets and the LinkedIn post are drafted only after real metrics
  exist, not before

---

## 12. Immediate next steps

In order:

1. Design the 50 golden questions (defines what "correct" means before any
   code is written against it)
2. Build the repo skeleton and `docker-compose.yml`
3. Write the semantic layer YAML for the chosen dataset
4. Begin Week 1, Day 1

---

*This plan supersedes earlier informal versions of the schedule discussed in
chat. If any section here conflicts with an earlier message, this document
is the source of truth going forward.*
