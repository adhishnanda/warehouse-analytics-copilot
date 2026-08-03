"""FastAPI backend: wraps the agent loop (src/agent/loop.py) as an HTTP
API for the Streamlit frontend (src/app/ui.py).

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
from pydantic import BaseModel

from src.agent.loop import answer_question
from src.config import AGENT_CHAT_BACKEND, OLLAMA_MODEL, OPENAI_MODEL, TRACE_LOG_PATH
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


def _jsonable(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.con = get_connection()
    app.state.retriever = Retriever()
    app.state.reranker = Reranker()
    yield
    app.state.con.close()


app = FastAPI(title="Warehouse Analytics Copilot", lifespan=lifespan)


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
    total_usage = {"total_tokens": sum(u.get("total_tokens", 0) for u in usage_records)} if usage_records else {}

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
    return AskResponse(
        query_id=query_id,
        question=request.question,
        sql=response.final_sql,
        columns=result.columns if result else [],
        rows=rows,
        row_count=result.row_count if result else 0,
        succeeded=response.succeeded,
        error=error,
        attempt_count=len(response.attempts),
        model=model,
    )


@app.post("/feedback")
def feedback(request: FeedbackRequest) -> dict:
    try:
        log_feedback(request.query_id, request.vote, path=TRACE_LOG_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
