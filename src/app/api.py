"""FastAPI backend: wraps the agent loop (src/agent/loop.py) as an HTTP
API for the React frontend (frontend/), and also serves that frontend's
built static assets directly (see the bottom of this file) so the whole
app is one process, one port, in production.

Retrieval and generation are unchanged from the production agent loop —
this file only adds the HTTP surface, per-request telemetry logging, and
chat-backend selection (AGENT_CHAT_BACKEND). Interactive use defaults to
the free local Ollama model, not the paid Day 11 production winner, so
running or demoing the app never spends money without an explicit
opt-in (see src/config.py).
"""

from __future__ import annotations

import datetime
import decimal
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agent.loop import answer_question
from src.app.chart import pick_chart_kind
from src.app.monitoring import router as monitoring_router
from src.config import (
    AGENT_CHAT_BACKEND,
    MAX_DAILY_QUERIES,
    OLLAMA_MODEL,
    OPENAI_MODEL,
    REPO_ROOT,
    RETRIEVAL_BACKEND,
    TRACE_LOG_PATH,
)
from src.db.duckdb_client import get_connection
from src.llm_client import chat_openai, chat_with_usage
from src.retrieval.reranker import Reranker
from src.retrieval.retriever import Retriever
from src.telemetry.logger import log_feedback, log_trace


def _build_chat_fn(backend: str):
    """Returns a (chat_fn, usage_records) pair for one request. usage_records
    is a fresh list per call, not a shared accumulator, so concurrent
    requests never mix each other's token usage.
    """
    usage_records: list[dict] = []

    if backend == "openai":

        def chat_fn(system_prompt: str, user_content: str) -> str:
            completion = chat_openai(system_prompt, user_content)
            usage_records.append(completion.usage)
            return completion.content

    else:

        def chat_fn(system_prompt: str, user_content: str) -> str:
            completion = chat_with_usage(system_prompt, user_content)
            usage_records.append(completion.usage)
            return completion.content

    return chat_fn, usage_records


def _model_name() -> str:
    return OPENAI_MODEL if AGENT_CHAT_BACKEND == "openai" else OLLAMA_MODEL


# Module-level, not per-request: a single process-wide counter is enough
# for a single-instance deploy (Render's free tier runs exactly one), and
# resets naturally on any restart, which is an acceptable, disclosed
# limitation for a portfolio demo's cost guard, not a strict SLA.
_rate_limit_state = {"date": None, "count": 0}


def _check_rate_limit() -> None:
    """Raises 429 once MAX_DAILY_QUERIES is hit, but only for the paid
    backend — local Ollama development is never limited.
    """
    if AGENT_CHAT_BACKEND != "openai":
        return
    today = datetime.date.today().isoformat()
    if _rate_limit_state["date"] != today:
        _rate_limit_state["date"] = today
        _rate_limit_state["count"] = 0
    if _rate_limit_state["count"] >= MAX_DAILY_QUERIES:
        raise HTTPException(
            status_code=429,
            detail=f"Daily query limit ({MAX_DAILY_QUERIES}) reached for the paid backend. Try again tomorrow.",
        )
    _rate_limit_state["count"] += 1


def _jsonable(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.con = get_connection()
    app.state.retriever = Retriever(backend=RETRIEVAL_BACKEND)
    app.state.reranker = Reranker(backend=RETRIEVAL_BACKEND)
    yield
    app.state.con.close()


app = FastAPI(title="Warehouse Analytics Copilot", lifespan=lifespan)
app.include_router(monitoring_router)


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    query_id: str
    question: str
    sql: str | None
    columns: list[str]
    rows: list[list]
    row_count: int
    succeeded: bool
    error: str | None
    attempt_count: int
    model: str
    chart_kind: str


class FeedbackRequest(BaseModel):
    query_id: str
    vote: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    _check_rate_limit()

    chat_fn, usage_records = _build_chat_fn(AGENT_CHAT_BACKEND)
    model = _model_name()

    start = time.perf_counter()
    response = answer_question(
        request.question,
        app.state.con,
        app.state.retriever,
        app.state.reranker,
        chat_fn=chat_fn,
    )
    latency = time.perf_counter() - start

    result = response.final_result
    last_attempt = response.attempts[-1] if response.attempts else None
    error = None
    if not response.succeeded:
        error = (last_attempt.error or last_attempt.validation_reason) if last_attempt else "no attempts made"
    total_usage = (
        {
            "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage_records),
            "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage_records),
            "total_tokens": sum(u.get("total_tokens", 0) for u in usage_records),
        }
        if usage_records
        else {}
    )

    query_id = str(uuid.uuid4())
    log_trace(
        query_id=query_id,
        question=request.question,
        sql=response.final_sql,
        succeeded=response.succeeded,
        error=error,
        attempt_count=len(response.attempts),
        row_count=result.row_count if result else None,
        latency_seconds=latency,
        model=model,
        usage=total_usage,
        path=TRACE_LOG_PATH,
    )

    rows = [[_jsonable(v) for v in row] for row in result.rows] if result else []
    columns = result.columns if result else []
    # Computed on the already-jsonable rows, not result.rows directly:
    # pick_chart_kind's numeric check excludes decimal.Decimal, so running
    # it before conversion would misclassify numeric columns.
    chart_kind = pick_chart_kind(columns, rows) if response.succeeded else "table"

    return AskResponse(
        query_id=query_id,
        question=request.question,
        sql=response.final_sql,
        columns=columns,
        rows=rows,
        row_count=result.row_count if result else 0,
        succeeded=response.succeeded,
        error=error,
        attempt_count=len(response.attempts),
        model=model,
        chart_kind=chart_kind,
    )


@app.post("/feedback")
def feedback(request: FeedbackRequest) -> dict:
    try:
        log_feedback(request.query_id, request.vote, path=TRACE_LOG_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


# Serves the built React SPA (frontend/), registered after every API route
# above so those always match first. Guarded on the build actually
# existing so tests/test_api.py's TestClient still works on a machine
# that hasn't run `npm run build`. The catch-all returns index.html for
# any unmatched path - plain StaticFiles(html=True) only does this for
# directory-index requests, not arbitrary client-side routes like
# /monitoring surviving a hard refresh.
_FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        return FileResponse(_FRONTEND_DIST / "index.html")
