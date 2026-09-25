FROM python:3.12-slim

WORKDIR /app
# WeasyPrint（报告 PDF 导出）需要 pango；中文报告需要 CJK 字体
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/src ./apps/api/src

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/apps/api/src"
EXPOSE 8000
CMD ["uvicorn", "patent_evidence_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
