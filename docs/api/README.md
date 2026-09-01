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
every request.
