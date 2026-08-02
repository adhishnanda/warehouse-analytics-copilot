# Project: Warehouse Analytics Copilot

Agentic text-to-SQL over a governed semantic layer, built as an LLM Zoomcamp
capstone. Full plan: see `PROJECT_PLAN.md` in this repo root — read it in
full before doing anything else, every session.

## What this is

A user asks a business question in English. The system rewrites the query,
retrieves relevant table/metric documentation from a semantic layer (hybrid
search + reranking), generates SQL grounded in that context, executes it
read-only against DuckDB, validates the result and retries on failure, then
returns the answer, the SQL, and a chart. Every exchange is logged for
monitoring.

## Non-negotiable rules

1. **Never fabricate metrics.** Every number in code comments, README,
   evaluation tables, or docstrings must come from an actual executed run.
   If something hasn't been measured yet, leave it blank or write
   "pending measurement" — never a plausible-looking placeholder number.
2. **Never mention Claude, Claude Code, Anthropic, or any AI tool** in:
   commit messages, README, code comments, docstrings, variable/file names,
   or any committed file. Write everything as if authored directly.
3. **Read-only DB access only.** The agent's SQL execution path must never
   have write permissions. Guardrails (read-only connection, SELECT-only
   whitelist, row limits, query timeout) live in `src/agent/guardrails.py`
   and must be tested, not just implemented.
4. **Follow the rubric exactly.** Section 3 of `PROJECT_PLAN.md` maps every
   build decision to a specific scoring criterion. Do not skip the "best
   practices" items (query rewriting, reranking, hybrid search evaluation)
   — they are worth real points, not polish.
5. **Cost discipline.** Use Groq free tier or Ollama for all development
   and iteration. Only use a paid model for the final, reproducible
   evaluation runs in Week 2. Flag before making any paid API call.
6. **UK English. No em dashes or en dashes except in date ranges.**
7. **Commit frequently, in small units**, with plain descriptive messages
   (imperative mood: "Add", "Fix", "Implement" — not "Added" or "Implements").

## Full completion required — no scope cuts

The goal is full marks on every rubric criterion in Section 3 of
`PROJECT_PLAN.md`: all 9 core criteria at max points, all 3 best-practice
items implemented and evaluated (hybrid search, reranking, query
rewriting), and the docker-compose/monitoring/reproducibility requirements
met exactly as specified. Nothing in the plan is a "nice to have" — treat
every item in Section 3's table as mandatory.

This will take multiple sessions, not one. Do not compress scope to fit a
single sitting. Instead, at the start of every session:

1. Read `PROJECT_PLAN.md`, this file, and `SESSION_LOG.md` in full
2. Work through the Week 1 → Week 2 → Week 3 order from Section 8 of
   `PROJECT_PLAN.md`, picking up exactly where the last session left off
3. Build each piece properly rather than stubbing it — a half-implemented
   reranker or a placeholder evaluation table is worse than an honestly
   incomplete `SESSION_LOG.md` that says what's left
4. Before ending a session, if something is genuinely unfinished, say so
   explicitly in `SESSION_LOG.md` with what remains — never mark something
   done in the log unless it actually is, since future sessions rely on
   that log being accurate

If a session runs out of time mid-task, stop at a clean boundary (e.g.
after a working, tested unit) rather than leaving broken code, and record
exactly where things stand.

## Repository structure

Follow the structure in Section 9 of `PROJECT_PLAN.md` exactly. Create
directories as needed; don't invent a different layout.

## Session workflow

At the start of every session:
1. Read `PROJECT_PLAN.md` and this file in full
2. Read `SESSION_LOG.md` (create it if it doesn't exist) to see what was
   done previously and what's still TODO
3. State a short plan for this session before writing code
4. At the end of the session, append a dated entry to `SESSION_LOG.md`:
   what was built, what was measured (with real numbers if any evaluation
   ran), and what's next

## Definition of done for the whole project

Match Section 3 of `PROJECT_PLAN.md` (the rubric scoring table) exactly,
at full marks on every line: all 9 core criteria, all 3 best-practice
items, real measured numbers in `evaluation/results/` for every evaluation
table. The bonus (cloud deployment) is the only genuinely optional item.
Nothing else is optional. The project is not "done" until every row in
that table is checked off with working, tested, honestly-documented code
— not until time runs out.

## When in doubt

Prefer a smaller, honestly-documented, fully-working piece over a larger
half-working one. A README section that says "not yet implemented, planned
for X" is acceptable. A fabricated metric or a broken feature described as
working is not.
