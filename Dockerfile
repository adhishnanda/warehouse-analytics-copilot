FROM python:3.13.7-slim-bookworm

RUN pip install --no-cache-dir uv==0.11.20

# torch (a sentence-transformers dependency) pulls several large NVIDIA
# CUDA packages we never use for CPU-only local inference; the default
# 30s per-request timeout is too tight for those downloads on a slower
# connection and fails the build with a network timeout, not a real
# error.
ENV UV_HTTP_TIMEOUT=300

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "data/seed_warehouse.py"]
