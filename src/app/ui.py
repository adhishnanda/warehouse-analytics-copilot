"""Streamlit frontend: ask a business question, see the answer, the SQL
that produced it, a chart, and give thumbs up/down feedback.

Talks to the FastAPI backend (src/app/api.py) over HTTP rather than
importing the agent loop directly, so the interface and the agent stay
independently deployable — PROJECT_PLAN.md Section 6: FastAPI backend +
Streamlit frontend.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.app.chart import pick_chart_kind, to_dataframe  # noqa: E402
from src.config import API_BASE_URL  # noqa: E402

SUGGESTED_QUESTIONS = [
    "How many orders do we have in total?",
    "What is total revenue by region?",
    "What is our repeat customer rate?",
]

st.set_page_config(page_title="Warehouse analytics copilot", page_icon=":material/database:")


@st.cache_resource
def get_http_client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE_URL, timeout=120.0)


def ask_question(question: str) -> dict:
    response = get_http_client().post("/ask", json={"question": question})
    response.raise_for_status()
    return response.json()


def send_feedback(query_id: str, vote: str) -> None:
    get_http_client().post("/feedback", json={"query_id": query_id, "vote": vote})


def _handle_vote(query_id: str, vote: str) -> None:
    try:
        send_feedback(query_id, vote)
    except httpx.HTTPError:
        pass
    st.session_state.votes[query_id] = vote


def _label(column: str) -> str:
    return column.replace("_", " ").capitalize()


def _format_value(value) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def render_feedback(query_id: str) -> None:
    votes = st.session_state.setdefault("votes", {})
    current_vote = votes.get(query_id)
    with st.container(horizontal=True):
        st.button(
            "Helpful",
            icon=":material/thumb_up:",
            key=f"vote_up_{query_id}",
            type="primary" if current_vote == "up" else "secondary",
            on_click=_handle_vote,
            args=(query_id, "up"),
            disabled=current_vote is not None,
        )
        st.button(
            "Not helpful",
            icon=":material/thumb_down:",
            key=f"vote_down_{query_id}",
            type="primary" if current_vote == "down" else "secondary",
            on_click=_handle_vote,
            args=(query_id, "down"),
            disabled=current_vote is not None,
        )
        if current_vote:
            st.caption("Thanks for the feedback.")


def render_answer(data: dict) -> None:
    if not data["succeeded"]:
        st.error(data["error"] or "The agent could not answer this question.")
        if data["sql"]:
            with st.expander("Attempted SQL"):
                st.code(data["sql"], language="sql")
        render_feedback(data["query_id"])
        return

    columns, rows = data["columns"], data["rows"]
    kind = pick_chart_kind(columns, rows)

    if kind == "metric":
        st.metric(_label(columns[0]), _format_value(rows[0][0]))
    elif kind == "kpi_row":
        with st.container(horizontal=True):
            for column, value in zip(columns, rows[0]):
                st.metric(_label(column), _format_value(value), border=True)
    elif kind == "bar":
        st.bar_chart(to_dataframe(columns, rows), x=columns[0], y=columns[1])
    elif kind == "line":
        st.line_chart(to_dataframe(columns, rows), x=columns[0], y=columns[1])
    else:
        st.dataframe(to_dataframe(columns, rows), hide_index=True)

    with st.expander("Show SQL"):
        st.code(data["sql"], language="sql")
    attempts = data["attempt_count"]
    st.caption(f"{data['model']} · {attempts} attempt{'s' if attempts != 1 else ''}")

    render_feedback(data["query_id"])


st.title("Warehouse analytics copilot")
st.caption(
    "Ask a business question in plain English. Answers are grounded in a "
    "governed semantic layer, not a raw schema dump."
)

st.session_state.setdefault("messages", [])
st.session_state.setdefault("votes", {})

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "user":
            st.write(message["content"])
        else:
            render_answer(message["data"])

selected = None
if not st.session_state.messages:
    selected = st.pills("Try asking:", SUGGESTED_QUESTIONS, label_visibility="collapsed")

prompt = st.chat_input("Ask a business question about the warehouse") or selected

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    data = None
    with st.chat_message("assistant"):
        try:
            with st.spinner("Retrieving context and generating SQL..."):
                data = ask_question(prompt)
        except httpx.HTTPError as exc:
            st.error(f"Could not reach the backend at {API_BASE_URL}: {exc}")

        if data is not None:
            render_answer(data)

    if data is not None:
        st.session_state.messages.append({"role": "assistant", "data": data})
