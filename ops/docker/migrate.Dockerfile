FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
COPY apps/api ./apps/api

ENV PATH="/app/.venv/bin:${PATH}"
CMD ["alembic", "-c", "apps/api/alembic.ini", "upgrade", "head"]
