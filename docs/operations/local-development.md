# Local development

Use Python 3.12 or later and current Node LTS. The checked-in `.env.example`
contains explicit development-only Compose defaults; copy it to `.env` only
locally and never promote those values to production.

```sh
uv sync --no-install-project --python /opt/homebrew/bin/python3.12
pnpm install
.venv/bin/pytest
./scripts/test-postgres.sh
pnpm test:web
pnpm build:web
.venv/bin/python scripts/verify-source-lock.py
.venv/bin/python scripts/verify-scaffold.py
docker compose up --build
```

The first Compose start creates four explicit PostgreSQL roles:
`patent_evidence_migration`, `patent_evidence_app`,
`patent_evidence_platform`, and `patent_evidence_worker`. Their checked-in
password defaults are development-only. Existing pre-P0-02 database volumes
must be recreated once with `docker compose down --volumes` before the role
bootstrap can run; this deletes local Compose database data.

Compose treats PostgreSQL readiness and the one-shot Alembic migration as
startup gates for API and worker services. The API `GET /health` endpoint is a
dependency-free liveness check, so it remains available for process diagnosis
even when PostgreSQL is unavailable after startup.

`./scripts/test-postgres.sh` starts a disposable PostgreSQL 16 container on a
random loopback port, applies Alembic as the migration owner, and runs the RLS
suite through the application, platform, and worker login roles. The container
and its data are removed on exit.

For focused process checks, run `PYTHONPATH=apps/api/src .venv/bin/uvicorn
patent_evidence_api.main:app --reload` or `PYTHONPATH=apps/worker/src
.venv/bin/python -m patent_evidence_worker.main health`.
