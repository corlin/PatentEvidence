# Local development

Use Python 3.12 or later and current Node LTS. The checked-in `.env.example`
contains explicit development-only Compose defaults; copy it to `.env` only
locally and never promote those values to production.

The checked-in MFA encryption key is also development-only. Every
non-development deployment must set `PATENT_EVIDENCE_MFA_ENCRYPTION_KEY` to a
separately generated Fernet key; startup rejects the checked-in development
key outside development.

Local Compose exposes password-reset tokens in the otherwise generic reset
response so the confirm flow is reproducible without an email adapter. The
setting is rejected outside development and must never be enabled in a shared
deployment.

Password-reset requests within the rate limits perform dummy Argon2 work for
both known and unknown identities. Every request applies a 200 ms minimum
response-time floor. The floor is injected in HTTP tests so the boundary is
verified without flaky wall-clock assertions. It is a minimum, not a promise of
identical network latency; use normal edge-level rate limiting and monitoring in
production as well.

Reset throttling checks both the socket-peer IP and a SHA-256-derived email key
before scheduling Argon2 work. Requests rejected by either process-local limit
still receive the same generic response and minimum floor, while avoiding KDF
resource consumption. Login verification, reset dummy work, and new-password
hashing all run through the API's worker-thread seam rather than on the async
event loop.

The default password-work pool allows 2 concurrent workers and 4 queued
requests. Configure it with `PATENT_EVIDENCE_PASSWORD_WORK_WORKERS` (1–4) and
`PATENT_EVIDENCE_PASSWORD_WORK_QUEUE` (0–16). Admission is non-blocking once the
combined running-plus-queued capacity is full; authentication returns a generic
503 and does not open a database transaction. The API closes its dedicated
executor during application shutdown. Keep these limits conservative because
each default Argon2 operation uses substantial memory.

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
