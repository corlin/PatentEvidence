FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Worker 与 API 共用 Python 领域包（spec §4.1）：patent_evidence_api、modules、adapters、prompts
COPY modules ./modules
COPY adapters ./adapters
COPY prompts ./prompts
COPY apps/api/src ./apps/api/src
COPY apps/worker/src ./apps/worker/src

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app:/app/apps/api/src:/app/apps/worker/src"
CMD ["python", "-m", "patent_evidence_worker.main", "service"]
