# P0-01 PatentEvidence repository scaffold

Authoritative product specification: `/Users/corlin/Documents/Codex/2026-08-31/zuo/outputs/patent-evidence-mvp-implementation-spec.md`

## Global constraints

- Build a new independent commercial repository. Do not merge source-project Git histories and do not use Git submodules.
- Product name is `PatentEvidence`; initial branch is `build/p0-scaffold`.
- Runtime baseline: Python 3.12+, FastAPI, React/TypeScript/Vite, PostgreSQL, S3-compatible object storage.
- The scaffold must be runnable and testable without implementing business features from weeks 1–6.
- Do not copy source-project runtime data, `.env` files, databases, credentials, cookies, customer files, generated artifacts, or local caches.
- `provenance/sources.lock.json` must contain the seven accepted sources and exact 40-character commits from the authoritative product specification.
- EPO and USPTO integrations are future pinned-binary/sidecar adapters. CNIPR is future manual-handoff-contract-only; the scaffold must not introduce direct HTTP, headless automation, cookie replay, or bulk collection.
- Production secrets must fail closed. The scaffold may define interfaces and environment names but no real secrets.
- The API health endpoint must not require a database connection, so container health can distinguish process health from dependency readiness.
- All committed text files must be UTF-8, and generated/cache/runtime paths must be ignored.

## Task 1: Create and verify the P0-01 scaffold

Create the initial repository baseline with these deliverables:

1. Root governance and developer files:
   - `README.md`, `AGENTS.md`, `.gitignore`, `.env.example`, `LICENSE`
   - `pyproject.toml`, `package.json`, `pnpm-workspace.yaml`, `compose.yaml`
2. Minimal runnable Python surfaces:
   - `apps/api/src/patent_evidence_api/main.py` with `GET /health` returning a stable JSON object.
   - `apps/worker/src/patent_evidence_worker/main.py` with a one-shot health command suitable for validation and a non-busy-loop service entrypoint.
   - Python package markers and focused tests for API and worker health behavior.
3. Minimal runnable React/Vite surface:
   - `apps/web` package, TypeScript/Vite config, a small page identifying the product and current P0 status.
   - A frontend unit test that verifies the visible product name and status.
4. Placeholder package/module/adapter boundaries matching the authoritative directory design. Use README files or package markers so Git tracks intentional empty boundaries; do not implement week 1–6 features.
5. Operations baseline:
   - Dockerfiles for API, worker and web.
   - Compose services for API, worker, web, PostgreSQL and MinIO with named volumes and health checks where appropriate.
   - No hard-coded production credentials; development-only defaults must be explicit in `.env.example` and compose interpolation.
6. Provenance baseline:
   - Copy the accepted source lock into `provenance/sources.lock.json`.
   - Add `provenance/DERIVATION_POLICY.md`, `provenance/FILE_MAP.md`, and `provenance/THIRD_PARTY_NOTICES.md`.
   - Include the MIT license notice text or clear vendoring instructions for `epo-cli` and `uspto-cli`; record owner-authorization requirements for repositories with no license file.
7. Documentation and validation:
   - Copy the accepted product specification to `docs/product/mvp-implementation-spec.md`.
   - Add architecture, local-development and source-upgrade notes.
   - Add `scripts/verify-source-lock.py` and `scripts/verify-scaffold.py`; both must exit nonzero on invalid state.
   - Add GitHub Actions CI that installs Python and Node dependencies and runs the Python tests, frontend tests/build, source-lock validation and scaffold validation.
8. Run all available focused and full validation commands, record exact output in the task report, self-review the diff, and commit all intended scaffold files.

Acceptance criteria:

- The source-lock verifier validates exactly seven unique names, unique repositories, and 40-character lowercase hexadecimal commits.
- The scaffold verifier checks required files/directories and rejects tracked secret/runtime patterns.
- Python tests pass and exercise the API health response and worker one-shot response.
- Frontend tests pass and the production frontend build succeeds.
- `docker compose config` succeeds when Docker Compose is available; if unavailable, record that limitation without claiming the check passed.
- `git status --short` is clean after the implementation commit except for the SDD workspace, which is ignored.
