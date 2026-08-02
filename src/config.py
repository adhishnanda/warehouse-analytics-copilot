"""Central configuration: paths, env vars, model names."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

DUCKDB_PATH = Path(os.environ.get("DUCKDB_PATH", REPO_ROOT / "data" / "warehouse.duckdb"))
TPCH_SCALE_FACTOR = float(os.environ.get("TPCH_SCALE_FACTOR", "0.1"))

SEMANTIC_LAYER_DIR = REPO_ROOT / "semantic_layer"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")
EVAL_MODEL_API_KEY = os.environ.get("EVAL_MODEL_API_KEY", "")
