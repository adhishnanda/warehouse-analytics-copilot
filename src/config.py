"""Central configuration: paths, env vars, model names."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

DUCKDB_PATH = Path(os.environ.get("DUCKDB_PATH", REPO_ROOT / "data" / "warehouse.duckdb"))
TPCH_SCALE_FACTOR = float(os.environ.get("TPCH_SCALE_FACTOR", "0.1"))
TRACE_LOG_PATH = Path(os.environ.get("TRACE_LOG_PATH", REPO_ROOT / "data" / "telemetry" / "traces.jsonl"))

# Separate from DUCKDB_PATH deliberately: the API holds a persistent
# read-only connection to the warehouse for the app's lifetime, and DuckDB
# allows only one read-write connection to a given file at a time. Loading
# telemetry into the same file would contend with that connection every
# time the dlt pipeline (src/telemetry/dlt_pipeline.py) runs.
TELEMETRY_DB_PATH = Path(os.environ.get("TELEMETRY_DB_PATH", REPO_ROOT / "data" / "telemetry.duckdb"))

# Week 3 interface (Section 5.5): interactive use defaults to the free local
# model so running or demoing the app never incurs API cost by accident.
# Set AGENT_CHAT_BACKEND=openai to use the Day 11 production winner
# (gpt-4o-mini) instead — see src/app/api.py.
AGENT_CHAT_BACKEND = os.environ.get("AGENT_CHAT_BACKEND", "ollama")

# Where the Streamlit UI (src/app/ui.py) finds the FastAPI backend.
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

SEMANTIC_LAYER_DIR = REPO_ROOT / "semantic_layer"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")

# Week 2 LLM evaluation (Section 7.3): Groq free tier + one small paid model.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
