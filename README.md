# PatentEvidence

PatentEvidence is a multi-tenant SaaS baseline for traceable patent evidence
workflows. This P0 repository scaffold deliberately contains no week 1–6
business features.

## P0 surfaces

- API process health: `GET /health` returns a dependency-free process status.
- Identity security: password login/reset, opaque 12-hour sessions, TOTP and
  one-time recovery codes under `/api/v1/auth`.
- Platform operations: MFA-gated organization provisioning, quota and lifecycle
  management under `/api/v1/platform/organizations`.
- Organization administration: 72-hour single-use invitations, fixed-role
  membership lifecycle, tenant-safe administration and last-admin protection
  under `/api/v1/organizations`; token inspection/acceptance under
  `/api/v1/invitations`.
- Worker process health: `python -m patent_evidence_worker.main health`.
- Web surface: a Vite/React page identifying PatentEvidence and P0 status.
- Provenance: seven immutable source records are checked by
  `scripts/verify-source-lock.py`.

## Local development

1. Copy `.env.example` to `.env` only for local development and replace the
   development-only values before sharing any environment.
2. Install Python dependencies with `uv sync --no-install-project --python
   /opt/homebrew/bin/python3.12` (or another Python 3.12+ interpreter).
3. Install frontend dependencies with `pnpm install`.
4. Run the validation sequence:

   ```sh
   .venv/bin/pytest
   ./scripts/test-postgres.sh
   pnpm test:web
   pnpm build:web
   .venv/bin/python scripts/verify-source-lock.py
   .venv/bin/python scripts/verify-scaffold.py
   docker compose config
   ```

5. Start the development stack with `docker compose up --build`. The one-shot
   `migrate` service must complete before the API and worker start. `GET
   /health` remains a process-liveness check and intentionally does not query
   PostgreSQL.

See `docs/operations/local-development.md` for process commands and
`docs/architecture/p0-scaffold.md` for boundaries.

## Source governance

The lockfile is an immutable inventory, not a production dependency list. Do
not use floating source revisions, copy source-project histories, or vendor
CLI source into the services. Follow `provenance/DERIVATION_POLICY.md` before
introducing a derivative file or updating a source.
