# PatentEvidence domain language

## Identity and authority

- **Global Identity** — one human sign-in identity shared across all organizations. It does not carry organization membership or platform authority by itself.
- **Session** — a revocable, time-bounded proof that a Global Identity authenticated. A Session never stores organization membership or role authority.
- **Session Authority** — the current validity of a Session and its Global Identity, including expiry, revocation, security-version invalidation, and recent MFA proof.
- **Platform Operator Grant** — the current authority for a Global Identity to perform platform-wide administration.
- **Organization Membership** — the current relationship and fixed role connecting a Global Identity to one Organization.

## Organization provisioning

- **Organization** — an isolated institution tenant opened manually by a Platform Administrator.
- **Organization Lifecycle** — the Organization's effective availability: active, suspended, or expired.
- **Quota Plan** — the Organization's manually assigned case allowance and current allowance period. It is not billing or payment.
- **Provisioning Request** — one idempotent attempt by a Platform Administrator to open an Organization.
- **Provisioning Record** — immutable evidence that an Organization and its Initial Administrator Invitation were created together.
- **Initial Administrator Invitation** — the one-time invitation issued while opening an Organization, granting the fixed organization_admin role when accepted.

## Evidence

- **Platform Audit Event** — immutable, secret-safe evidence of an attempted platform-wide privileged action, whether allowed, denied, or failed.
- **Request Correlation ID** — a safe identifier connecting one attempted action to its Platform Audit Event.
