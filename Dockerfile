FROM python:3.13.7-slim-bookworm

RUN pip install --no-cache-dir uv==0.11.20

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "data/seed_warehouse.py"]
