FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/src ./apps/api/src

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/apps/api/src"
EXPOSE 8000
CMD ["uvicorn", "patent_evidence_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
