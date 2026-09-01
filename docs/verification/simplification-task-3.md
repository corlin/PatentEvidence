# Simplification and P0-02 Task 3 acceptance

Verified: 2026-09-02, local development environment.

Implementation baseline: `b24d013`. Implementation commits: `72ab998`,
`6be2342`, `1a138e5`. This report closes the approved six simplification
recommendations and P0-02 Task 3, not the entire P0-02 phase.

## Recommended simplifications

| Recommendation | Current implementation | Verification evidence |
| --- | --- | --- |
| Consolidate session authority | `auth/session_authority.py` owns session/identity validity, security-version checks, locking and recent MFA; auth routes and guards consume it. | `test_authentication_api.py` covers expiration, revocation, MFA, concurrent authentication/reset and role boundaries. |
| Deepen role/context transactions | `core/database.py` provides explicit application, session-token, tenant, platform and worker transaction entrypoints; callers no longer assemble identity transaction recipes. | `test_database_context.py` verifies actual restricted roles, context binding, missing context and wrong-role rejection. |
| Consolidate privileged platform operations | `platform/access.py` owns application authentication followed by separate platform authorization, transaction and mutation evidence. | Platform provisioning and MFA-reset tests cover allowed, denied and failed operations, actor/target retention and rollback. |
| Resolve organization lifecycle semantics | ADR 0002 defines derived expiry; migration 0002 restricts persisted statuses to active/suspended. `OrganizationLifecycle` projects effective status; authorization retains the equivalent SQL predicate at the database boundary. | Controlled-clock expiry, reactivation conflict, clearing expiry, independent quota status and persisted-expired constraint tests pass. |
| Centralize platform audit rules | `PlatformAuditWriter` and `PlatformAccess` own safe fields, correlation and accepted/rejected/failed transaction placement. Bootstrap has an explicit migration-role audit adapter; existing MFA-reset SQL retains its atomic successful audit. | Tests cover malformed requests, missing keys, invalid target UUID, missing target, stale MFA, weak bootstrap password and injected database/audit failures without secret disclosure. |
| Consolidate PostgreSQL test adapters | `tests/test_support` owns role-checked URLs, settings, TOTP generation and standard login; fixtures retain explicit actors and organization scopes. | The complete real-role PostgreSQL suite passes through the shared adapters. |

`CONTEXT.md` records the domain language. ADR 0001 preserves the two distinct
application/platform transactions and least-privilege roles. Source derivation
records remain in `provenance/FILE_MAP.md` against the pinned PatentQ commit.

## Task 3 deliverables

| Plan requirement | Evidence |
| --- | --- |
| First administrator bootstrap, secure password input, bounded MFA handoff | `scripts/bootstrap-platform-admin.py`; subprocess tests prove first-only behavior, no positional password, weak-password rejection and secret-safe output; HTTP tests prove enrollment confirmation before/after the deadline. |
| Authenticated organization create/list/detail/suspend/reactivate/expiry | `platform/api.py`, `OrganizationProvisioner`, `OrganizationDirectory`; lifecycle API tests and non-platform create/read/mutation rejection. |
| Manual quota fields without billing | Organization creation/detail responses and `organization_plan_quotas`; allowance, period and effective-status assertions. |
| Atomic organization, initial administrator invitation and provisioning record | Creation/count assertions plus injected successful-audit failure prove the enclosing transaction rolls back all business records and idempotency state. |
| Thin organization CLI | `scripts/create-organization.py`; a real subprocess sends the documented JSON, cookie and idempotency header to a local HTTP server. |
| Immutable, secret-safe platform mutation audit | Restricted-role audit immutability tests; rejected request and failure tests. Failed business transactions write failure evidence in a separate transaction. |
| Actor-bound idempotency and conflict behavior | Same-key replay, conflicting payload, concurrent duplicate request, slug conflict and a second actor using the same key are exercised. Replays do not reveal the invitation token again. |
| CLI/API/transaction/idempotency/expiry/suspension/audit tests | `test_platform_cli_contract.py`, `test_platform_provisioning_api.py`, `test_authentication_api.py`, and database integration tests. |

## Independent review

- Specification review: final Critical 0, Important 0.
- Engineering standards review: final Critical 0, Important 0.
- Two fix rounds closed audit-validation gaps, missing actor/target evidence,
  bootstrap rollback evidence and missing public-seam proofs. Provisioning was
  separated from directory/lifecycle responsibilities.

## Fresh verification

All commands below exited successfully against implementation `1a138e5`:

- `./scripts/test-postgres.sh`: 63 passed; fresh upgrade and
  `0002 -> 0001 -> 0002` migration round trip passed.
- `uv run pytest`: 23 passed, 63 PostgreSQL-gated skipped. Those 63 tests were
  executed separately by the preceding PostgreSQL command.
- `pnpm test:web`: 1 passed.
- `pnpm build:web`: TypeScript check and production build passed.
- `uv run ruff check apps/api/src apps/api/tests scripts`: passed.
- Ruff format check on all 19 changed Python files: passed.
- Python compileall for API sources and scripts: passed.
- Source-lock verifier: 7 unique sources validated.
- Scaffold verifier and `docker compose config`: passed.
- Git whitespace checks: passed.

## Boundaries

- This is local validation, not production deployment or a production-readiness claim.
- Invitation acceptance and organization membership administration remain Task 4;
  browser administration remains Task 5; phase-wide release/security gates remain Task 6.
- Database-backed audit cannot guarantee persistence while the database itself is
  unavailable. Bootstrap audit attempts fail safely without printing credentials.
- No remote push, main-branch merge or deployment was performed for this batch.
