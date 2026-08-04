# Setup

Two ways to run this project: the full containerized stack (recommended,
matches exactly what was verified live), or a local, non-Docker setup for
development/iteration. Both are documented below. Either way, start with
the prerequisites and environment file.

## Prerequisites

- **Docker Desktop** (for the container path). This project was built
  and verified on Windows with Docker Desktop; the compose file has no
  Windows-specific assumptions beyond the two documented quirks in
  [Known platform quirks](#known-platform-quirks) below.
- **[uv](https://docs.astral.sh/uv/)** `0.11.20` (for the local path). It
  pins its own Python 3.13.7, so a separate Python install isn't required.
- **[Ollama](https://ollama.com)**, running locally with the `llama3`
  model pulled (`ollama pull llama3`). This is the default, free model
  the system uses for query rewriting and SQL generation. Nothing in this
  project calls a paid API unless you explicitly opt in (see
  [Using the paid backend](#using-the-paid-backend-optional) below).
- An **OpenAI API key**, only if you want to reproduce the paid-model
  evaluation results or use `gpt-4o-mini` as the interactive backend.
  Entirely optional; the system is fully functional without one.

## Environment file

```bash
cp .env.example .env
```

`.env.example` documents every variable; the defaults are already correct
for local, no-cost use. The ones worth knowing about:

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where the local model server is. Not used by the containerized `api` service (see below), only by `uv run` on the host and by the evaluation scripts. |
| `AGENT_CHAT_BACKEND` | `ollama` | `ollama` (free, default) or `openai` (paid, opt-in). |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | empty / `gpt-4o-mini` | Only read if `AGENT_CHAT_BACKEND=openai`. |
| `DUCKDB_PATH` | `data/warehouse.duckdb` | Warehouse file location. |
| `TRACE_LOG_PATH` | `data/telemetry/traces.jsonl` | Where every `/ask`/`/feedback` call is logged. |

`.env` is gitignored. Never commit real API keys.

## Option A: full containerized stack (recommended)

```bash
docker compose up --build
```

This builds one shared image (`warehouse-analytics-copilot:latest`,
built via a multi-stage Dockerfile that compiles the React frontend in a
Node stage before the final Python stage) and brings up four services:

| Service | What it does | Port |
|---|---|---|
| `seed` | Generates the TPC-H star schema and builds the retrieval indices, then exits | none |
| `api` | FastAPI backend, and serves the built React frontend (Ask + Monitoring pages) as static assets on the same port | `8000` |
| `kestra-db` | Postgres, Kestra's metadata store | internal only |
| `kestra` | Kestra orchestrator (`server standalone`), runs the nightly refresh flow and the daily synthetic-traffic flow | `8081` |

`api` shares one named volume (`warehouse_data`) with `seed`, so the
warehouse and indices `seed` builds are immediately visible to `api`,
including after Kestra's flow refreshes them later, with no restart
needed.

**Verify it's actually working, not just "up":**

```bash
curl http://localhost:8000/health          # {"status":"ok"}
```

Then open:
- `http://localhost:8000/ask`: ask a question (try one of the suggestion
  pills), confirm you get an answer with an SQL disclosure
- `http://localhost:8000/monitoring`: confirm the monitoring dashboard
  loads (it will be mostly empty until you've asked a few questions)
- `http://localhost:8081`: Kestra's own UI; both flows
  (`orchestration/kestra/refresh_flow.yml`,
  `orchestration/kestra/synthetic_traffic_flow.yml`) should be visible
  under Flows once imported (see the platform quirk on flow import below)

By default, `api` uses the free local Ollama backend and answers
`http://host.docker.internal:11434`. Ollama itself is **not**
containerized; it runs once on your host and is shared by every consumer
(the host CLI, evaluation scripts, and the containerized API alike).
Make sure `ollama serve` is running and `llama3` is pulled before asking
a question through the UI.

To bring everything down: `docker compose down` (add `-v` only if you
want to discard the named volumes and force a full reseed next time).

### Using the paid backend (optional)

The committed `docker-compose.yml` deliberately never interpolates
`OPENAI_API_KEY` into a file, since `docker compose config` (without
`--quiet`) prints any interpolated secret in plaintext. Two ways to opt
in to `gpt-4o-mini` for a session:

```bash
# One-off, for a single command:
docker compose run -e OPENAI_API_KEY=sk-... -e AGENT_CHAT_BACKEND=openai api ...

# Or create a local, gitignored docker-compose.override.yml:
```
```yaml
services:
  api:
    environment:
      - AGENT_CHAT_BACKEND=openai
      - OPENAI_API_KEY=${OPENAI_API_KEY}
```
Compose merges `docker-compose.override.yml` automatically if present.
Costs a fraction of a cent per question at OpenAI's published `gpt-4o-mini`
pricing (see `evaluation/results/llm_eval.md` for real measured token
costs from this project's own evaluation runs).

## Option B: local, non-Docker setup

Useful for development, running tests, or iterating quickly without a
Docker build. Needs [Node.js](https://nodejs.org) 24+ in addition to the
prerequisites above, for the frontend dev server.

```bash
uv sync                                   # installs the pinned environment (uv.lock)
uv run python scripts/seed_and_index.py   # generates the warehouse and retrieval indices
cd frontend && npm install                # installs the frontend's own dependencies
```

Then, in separate terminals:

```bash
uv run uvicorn src.app.api:app --reload
cd frontend && npm run dev
```

The frontend dev server runs on `:5173` and proxies `/ask`, `/feedback`,
`/health`, and `/monitoring/*` to the API on `:8000` (see
`frontend/vite.config.ts`), so open `http://localhost:5173` while
iterating. `OLLAMA_BASE_URL` resolves to `http://localhost:11434`
directly here (no `host.docker.internal` indirection needed on the host
path). To check the production-like single-port setup instead
(`http://localhost:8000` serving everything), build the frontend first:
`cd frontend && npm run build`, then just run the `uvicorn` command above.

## Running the tests

```bash
uv run pytest
```

298 tests as of the last full run on this repo (`uv run pytest -q`),
covering the warehouse schema, semantic layer and warehouse consistency,
retrieval, reranking, query rewriting, agent guardrails and loop, the
golden question set (every gold SQL statement is re-executed against the
live warehouse on every test run), the API and monitoring endpoints,
telemetry, the dlt pipeline, the monitoring dashboard's metric functions,
both Kestra flows' structure, the synthetic-traffic generator's sampling
and feedback-simulation logic, and the `docker-compose.yml` structure. A
handful of tests are conditionally skipped if Ollama or Docker isn't
reachable in your environment; this is by design (see individual test
files), not a failure. The frontend has no separate automated test suite
yet - `npm run build` type-checks it, and every change to it in this
project has been verified live in a real browser rather than left
unverified (see `SESSION_LOG.md`).

## Reproducing the evaluation numbers

Every table in the README's Evaluation section and every file in
`evaluation/results/` was produced by one of these scripts, run against
the real warehouse and a real model:

```bash
uv run python evaluation/run_retrieval_eval.py       # free, local embeddings only
uv run python evaluation/run_llm_eval.py              # local llama3 arm is free;
                                                       # gpt-4o-mini arm needs OPENAI_API_KEY and costs real money
uv run python evaluation/run_self_correction_eval.py  # needs OPENAI_API_KEY, paid
uv run python evaluation/run_ablation.py              # needs OPENAI_API_KEY for one arm, paid
uv run python evaluation/run_error_analysis.py        # needs OPENAI_API_KEY, paid
```

Rerunning the paid-model scripts will not reproduce the exact same
numbers, since the OpenAI API is not called at a pinned temperature. See
the variance note in `evaluation/results/self_correction_eval.md`. Costs
for each script (from real, measured API usage, not estimates) are
disclosed in their respective `evaluation/results/*.md` reports; none
exceeded a few cents.

## Populating the monitoring dashboard

`orchestration/kestra/synthetic_traffic_flow.yml` runs
`scripts/generate_synthetic_traffic.py` once a day so the Monitoring page
has ongoing activity between real sessions, rather than staying empty.
Every trace it produces is a genuine agent execution against the real
warehouse and the free local Ollama backend (never a paid model on its
own); only the choice of questions (sampled from
`evaluation/golden_questions.jsonl`) and simulated feedback votes are
scripted. To generate a batch by hand instead of waiting for the
schedule:

```bash
uv run python scripts/generate_synthetic_traffic.py       # 12 questions, default
uv run python scripts/generate_synthetic_traffic.py 25    # or a custom count
```

## Known platform quirks

These were found and fixed by actually running the stack, not anticipated
in advance. They're recorded here so they don't cost you the same
debugging time.

- **Kestra's Docker task runner needs the Docker socket, which needs root
  on Windows.** `docker-compose.yml`'s `kestra` service already runs as
  `user: "root"` and mounts `/var/run/docker.sock` for this reason, a
  known Docker-Desktop-on-Windows permission quirk (the image's default
  non-root user gets `Permission denied` on the socket otherwise). No
  action needed; noted in case you see this running Kestra a different way.
- **Kestra's Docker task runner overrides the image's working directory.**
  If you ever edit `orchestration/kestra/refresh_flow.yml`, keep the
  `cd /app &&` prefix on both task commands. Kestra's Docker task runner
  sets its own per-task scratch directory as the container's `WORKDIR`,
  silently ignoring the image's own `WORKDIR /app`.
- **`docker compose config` (without `--quiet`) prints resolved secrets in
  plaintext**, because Compose auto-loads `.env` for `${VAR}`
  interpolation and dumps fully-resolved values. Use
  `docker compose config --quiet` to validate the file's syntax without
  this risk (that's what `tests/test_docker_compose.py`'s live test does).
- **Importing flows into a running Kestra container needs its own CLI,
  not curl.** `docker exec <kestra-container> sh /app/kestra flow
  updates --no-delete <dir-inside-container> --server
  http://localhost:8080` is the working invocation (copy the flow YAML
  files in first with `docker cp orchestration/kestra
  <container>:/tmp/kestra-flows`; note `/app/kestra` is a hybrid
  sh/batch launcher, so it must be run as `sh /app/kestra ...`, not
  executed directly, and Git Bash on Windows needs
  `MSYS_NO_PATHCONV=1` prefixed to `docker exec`/`docker cp` calls with
  Unix-style container paths, or it mangles them into host paths).
  `kestra flow validate --local <file>` (no server round-trip) is a
  reliable way to check a flow's syntax against the real schema even
  when the step below isn't working.
- **Kestra OSS made basic auth mandatory as of 0.24.0 - the
  `basic-auth.enabled` config key is now ignored**, so
  `docker-compose.yml`'s original `enabled: false` setting did nothing;
  every API call (including ones that should be public, like the setup
  page's own submission endpoint) returned 401 regardless. Confirmed
  against Kestra's own migration/troubleshooting docs, not guessed:
  credentials must be set explicitly under `kestra.server.basic-auth`
  (`username`/`password`), which `docker-compose.yml` now does (same
  local-orchestration-credential pattern as `kestra-db`'s Postgres
  password already in that file - not a secret protecting real data).
- **Open item: even with real credentials configured, and a completely
  fresh `kestra_db_data`/`kestra_storage` volume, every `/api/v1/*`
  endpoint still returns 401** for this exact `kestra/kestra:v1.3.30`
  image - confirmed this isn't specific to the new flow (the
  already-working `refresh_flow.yml` hits the identical wall), and isn't
  a leftover-state issue (reproduced from a wiped metadata store). Not
  resolved within a reasonable timebox: no browser was available in that
  session to check whether the interactive `/ui/main/setup` flow
  succeeds where the API does (the SPA shell itself always returns 200
  regardless of backend auth state, so hitting that URL with curl proves
  nothing). If you hit this, try completing setup through the UI in a
  real browser first (`http://localhost:8081`); if that also fails,
  importing a flow via Flows -> Create in the UI is the fallback once
  you're past login.
