FROM node:24.11.1-bookworm-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

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

# Static SPA assets the api service serves directly (src/app/api.py) -
# built in the frontend-build stage so the final image never needs Node.
COPY --from=frontend-build /frontend/dist ./frontend/dist

ENV PATH="/app/.venv/bin:$PATH"

# Default single-process entrypoint: seed the warehouse, build the
# retrieval indices, then serve. docker-compose.yml's seed/api services
# override this explicitly per-service and don't depend on it - this
# default exists for a single-container run outside compose (Render's
# Blueprint deploy, or a plain `docker run`). ${PORT:-8000} picks up a
# host's dynamically assigned port when set (Render always sets one),
# falling back to 8000 otherwise.
CMD ["sh", "-c", "python scripts/seed_and_index.py && uvicorn src.app.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
