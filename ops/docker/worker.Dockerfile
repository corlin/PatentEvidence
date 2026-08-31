FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/worker/src ./apps/worker/src

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/apps/worker/src"
CMD ["python", "-m", "patent_evidence_worker.main", "service"]
