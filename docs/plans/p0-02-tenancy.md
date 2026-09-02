# P0-02 Multi-tenant identity and platform provisioning

Authoritative product specification: `docs/product/mvp-implementation-spec.md`

## Objective

Deliver the first production-shaped security boundary for PatentEvidence: real PostgreSQL tenancy, platform-admin organization provisioning, server-side sessions, basic MFA, fixed roles, invitations, quotas, audit evidence, and a minimal browser administration surface.

This phase does not implement patent cases, document upload, retrieval, evidence analysis, billing, public signup, or payment.

## Global constraints

- Use Python 3.12+, FastAPI, SQLAlchemy async, Alembic, PostgreSQL 16, React/TypeScript/Vite.
- The API, not the browser, is the authorization boundary. Never trust `organization_id`, user ID, or roles supplied in headers or request bodies when they can be derived from the authenticated session.
- All organization-scoped business tables contain `organization_id`, use composite tenant-safe foreign keys where applicable, and enable `FORCE ROW LEVEL SECURITY`.
- Cross-tenant resource access returns a safe 404 unless the request is an explicitly authorized platform operation.
- PostgreSQL integration tests must connect through the same restricted roles used by the API, not only a migration-owner or superuser connection.
- Platform operations use a separate database role and separate route guard from organization operations.
- Passwords use Argon2. Session, invitation, reset, recovery, and bootstrap tokens are random, single-purpose, time-bounded, and stored only as hashes.
- Browser authentication uses an opaque server-side session in an HttpOnly cookie named `pe_session`; no JWT is stored in browser storage.
- MFA uses TOTP. MFA seed material must be encrypted at rest with a deployment-provided key; production startup or enrollment fails closed when that key is absent or a documented development key is used outside development.
- Privileged roles (`platform_admin`, `organization_admin`) require confirmed MFA before privileged actions. Recovery material is shown once and stored only as hashes.
- Fixed MVP roles are exactly `platform_admin`, `organization_admin`, `patent_agent`, and `reviewer`. Do not implement custom roles.
- Public signup, online payment, billing tables, patent-case tables, email delivery, and generalized policy engines are out of scope.
- Audit events contain actor, action, target, result, timestamp, request correlation ID, and a safe summary. They never contain passwords, tokens, TOTP seeds, cookies, document text, or provider secrets.
- Source reuse is selective. Do not copy PatentQ environment files, databases, secrets, runtime data, or Git history. Record materially derived files in `provenance/FILE_MAP.md` against PatentQ commit `eb63654464e51fa0d68027679c6626fb2a0c608b`.
- Tests follow vertical TDD slices at these pre-agreed public seams: HTTP API, platform/admin CLI, real PostgreSQL/RLS connections, and browser-visible UI. Do not test private helpers as the primary proof of behavior.
- Each task commits its intended changes and leaves the worktree clean except for the ignored `.superpowers/` workspace.

## Task 1: PostgreSQL roles, migrations, tenant context, and RLS proof

Create the database foundation used by all later P0-02 tasks.

Deliverables:

1. Add SQLAlchemy async, asyncpg, Alembic, pydantic-settings, and PostgreSQL test dependencies with reproducible lock updates.
2. Add settings and database modules under `apps/api/src/patent_evidence_api/core/`.
3. Add Alembic configuration and initial migrations for:
   - `global_identities`
   - `organizations`
   - `organization_memberships`
   - `organization_plan_quotas`
   - `user_sessions`
   - `platform_operator_grants`
   - `organization_invitations`
   - `password_reset_tokens`
   - `mfa_credentials`
   - `mfa_recovery_codes`
   - `audit_events`
   - `platform_audit_events`
4. Create explicit database roles for migration owner, application, platform operation, and worker usage. Compose may bootstrap these roles from development-only credentials.
5. Add helpers that bind `app.current_organization_id` and actor/request context within a transaction. Organization-scoped repositories must not run without tenant context.
6. Enable and force RLS for organization-scoped tables. Use tenant-safe composite keys where child records reference organization records.
7. Add a dedicated PostgreSQL integration-test service or script that provisions a disposable database, migrates it, and connects through restricted roles.
8. Write real integration tests proving:
   - Organization A cannot select or mutate Organization B rows through the application role.
   - Missing tenant context sees no tenant rows and cannot insert tenant rows.
   - The platform role can provision organizations but cannot read user password hashes or MFA ciphertext through a broad table grant.
   - Audit rows cannot be updated or deleted through application/platform roles.
9. Update Compose health/readiness and local-development documentation.

Acceptance:

- Alembic upgrade succeeds against a fresh PostgreSQL 16 database.
- Restricted-role RLS tests pass against real PostgreSQL.
- Existing API/worker/web tests still pass.

## Task 2: Password authentication, opaque sessions, and MFA

Implement identity authentication through public HTTP seams.

Deliverables:

1. Add password hashing/verification with Argon2 and password policy validation.
2. Add login, logout, current-session, password-reset request/confirm, and session-revocation APIs.
3. Session tokens are at least 256 bits, stored as SHA-256 hashes, rotated on successful authentication, expire after 12 hours, and are delivered in `pe_session` with HttpOnly and SameSite=Lax. `Secure` is mandatory outside development.
4. Login and reset-request responses are resistant to user enumeration. Authentication errors do not reveal whether an email exists.
5. Add TOTP enrollment, confirmation, challenge, recovery-code use, and MFA reset by an authorized higher-level administrator.
6. Encrypt TOTP seeds with a deployment key. Recovery codes are shown once, individually hashed, one-time use, and invalidated on regeneration.
7. Privileged API guards require both a valid session and recent MFA verification for `platform_admin` and `organization_admin` operations.
8. Add rate-limit hooks/interfaces and deterministic development implementation; do not introduce Redis in P0-02.
9. Write API/integration tests for successful login, generic failures, cookie attributes, expiration, rotation, logout, reset-token one-time use, TOTP, recovery codes, and privileged step-up.

Acceptance:

- The public API tests observe all behavior without querying private helper state.
- No token, password, TOTP seed, recovery code, or cookie appears in audit/log test captures.

## Task 3: Platform-admin bootstrap, organization provisioning, quotas, and platform audit

Implement the operator flow for manually opening institutions.

Deliverables:

1. Add `scripts/bootstrap-platform-admin.py`:
   - Creates the first global identity and `platform_admin` grant only when none exists.
   - Accepts password through a secure prompt or environment injected at invocation; never a positional command argument.
   - Produces a bounded MFA enrollment handoff without logging secret material.
2. Add authenticated platform APIs to create, view, suspend, reactivate, and set expiry for organizations.
3. Add quota fields: plan key, monthly case allowance, current period start/end, and status. Do not implement billing or payment.
4. Creating an organization also creates its first `organization_admin` invitation and a provisioning record atomically.
5. Add `scripts/create-organization.py` as a thin API/command client for the same service behavior; do not duplicate domain logic.
6. Append immutable platform audit events for every attempted privileged mutation, including rejected attempts with safe summaries.
7. Add idempotency protection for organization creation using an `Idempotency-Key` bound to the platform actor and request fingerprint.
8. Write CLI, API, transaction, idempotency, expiry, suspension, and audit tests.

Acceptance:

- A platform admin can create an organization and one-time admin invitation in one transaction.
- Repeating the same idempotency key does not create duplicates; conflicting payload returns 409.
- A non-platform principal cannot access platform routes.

## Task 4: Invitations, memberships, fixed roles, and organization administration

Implement the organization administrator flow.

Deliverables:

1. Add invitation create, inspect, accept, revoke, and resend-as-new-token APIs.
2. Invitation tokens expire after 72 hours, are single-use, stored hashed, and bound to email, organization, and one fixed organization role.
3. Accepting an invitation creates or links a global identity and creates one active organization membership atomically.
4. Add member listing, role change, suspension, reactivation, and removal APIs.
5. Prevent removal/suspension/demotion of the last active organization administrator.
6. Derive active organization from the URL plus authenticated membership; never accept role or organization authority from custom headers.
7. Add safe 404 behavior for cross-tenant member/invitation IDs.
8. Add organization audit events for accepted and rejected mutations.
9. Write API and real PostgreSQL tests for invitation races, reuse, expiry, fixed-role validation, last-admin protection, and complete A/B cross-tenant matrices.

Acceptance:

- Organization A administrators cannot discover Organization B memberships or invitation state.
- Patent agents and reviewers cannot administer memberships.
- Audit records identify actor/action/target/result without token or credential data.

## Task 5: Minimal login, MFA, platform, and organization web surfaces

Build the browser surface required to operate P0-02 without curl.

Deliverables:

1. Add typed API client and session provider; rely on HttpOnly cookie, never localStorage/sessionStorage tokens.
2. Add login, MFA challenge/enrollment, and password-reset screens.
3. Add a platform organization list/create/detail screen with status, expiry, quota, suspend, and reactivate actions.
4. Add an organization member/invitation screen with role, status, revoke, resend, suspend, reactivate, and last-admin error presentation.
5. Add an explicit organization selection screen for users with more than one membership.
6. Add loading, empty, error, unauthorized, expired-session, and cross-tenant-safe not-found states.
7. Add accessibility-focused component tests and API-contract tests. Do not add a new component framework.
8. Keep P0 product visual language restrained and usable; no dashboard analytics, billing UI, patent-case UI, or speculative navigation.

Acceptance:

- Browser tests prove a platform admin can create an organization and an organization admin can invite a patent agent using real API contracts or the established contract fixture boundary.
- Tokens and authority data are absent from browser storage.
- Frontend typecheck, tests, and production build pass.

## Task 6: Security closure, operational docs, and P0-02 release gates

Close the phase with end-to-end security and operations evidence.

Deliverables:

1. Add a complete role/action authorization matrix and executable contract/security tests.
2. Add end-to-end tests for:
   - bootstrap platform admin
   - enroll/confirm MFA
   - create organization and invitation
   - accept organization-admin invitation
   - invite and activate a patent agent
   - Organization A attempts to access Organization B resources
   - suspend organization and reject its future sessions
3. Add production configuration validation for database role URLs, cookie security, allowed origins, MFA encryption key, and bootstrap disablement.
4. Add runbooks for initial bootstrap, organization provisioning, credential rotation, session revocation, suspension/reactivation, backup/restore ownership, and security incident containment.
5. Update README, API documentation, architecture documentation, `provenance/FILE_MAP.md`, and validation evidence.
6. Add `scripts/verify-p0-02.py` that fails unless required migrations, routes, tests, security matrices, runbooks, and source derivation records exist.
7. Run the complete Python suite, real PostgreSQL integration/security suite, frontend tests/build, all repository verifiers, Compose configuration, migration upgrade/downgrade/upgrade, and secret-pattern scans.

Acceptance:

- All release gates pass with fresh output.
- No Critical or Important code-review findings remain.
- The phase is not labeled production-ready unless a real production secret-store/configuration check has been performed; local validation is labeled accurately.
