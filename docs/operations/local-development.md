# Local development

Use Python 3.12 or later and current Node LTS. The checked-in `.env.example`
contains explicit development-only Compose defaults; copy it to `.env` only
locally and never promote those values to production.

```sh
uv sync --no-install-project --python /opt/homebrew/bin/python3.12
pnpm install
.venv/bin/pytest
pnpm test:web
pnpm build:web
.venv/bin/python scripts/verify-source-lock.py
.venv/bin/python scripts/verify-scaffold.py
docker compose up --build
```

For focused process checks, run `PYTHONPATH=apps/api/src .venv/bin/uvicorn
patent_evidence_api.main:app --reload` or `PYTHONPATH=apps/worker/src
.venv/bin/python -m patent_evidence_worker.main health`.
