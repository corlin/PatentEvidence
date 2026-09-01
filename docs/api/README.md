# API documentation

The P0 identity surface is rooted at `/api/v1/auth` and provides password
login, logout, current-session projection, all-session revocation, password
reset, TOTP enrollment/confirmation/challenge, and recovery-code rotation.

Privileged MFA reset is available to a recently MFA-verified platform
administrator at `/api/v1/platform/identities/{identity_id}/mfa/reset`, and to
a recently MFA-verified organization administrator for a lower-level member at
`/api/v1/organizations/{organization_id}/members/{identity_id}/mfa/reset`.

The `pe_session` cookie is opaque and identity-only. Organization and role
authority are never stored in it or in `user_sessions`; privileged guards
re-read the current platform grant or URL-scoped organization membership on
every request. Sessions also capture the identity security version and become
invalid immediately when a password reset advances that version.

Platform endpoints authenticate the opaque session in a short application-role
transaction, then close it before rechecking platform authority and performing
the mutation in a separately verified platform-role transaction. The platform
role has no session-table access. Organization administration remains in an
application-role, URL-tenant-bound transaction.

TOTP replacement keeps the confirmed factor active until the pending factor is
successfully confirmed. The database permits at most one active and one pending
factor per identity; confirmation atomically retires the old factor, promotes
the pending factor, and rotates the session.
