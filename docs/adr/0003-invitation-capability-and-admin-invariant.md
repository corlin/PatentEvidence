# ADR 0003: Treat invitations as capabilities and serialize administrator loss

- Status: Accepted
- Date: 2026-09-02

## Context

An Organization Invitation must reveal its Organization before a tenant context
can be bound, yet the application role must not gain general cross-tenant read
access. Invitation acceptance may create a Global Identity and Membership, and
concurrent attempts must not create duplicates. Concurrent membership changes
must never remove every active Organization Administrator.

## Decision

Persist only a SHA-256 invitation-token hash. A dedicated, SELECT-only RLS
policy exposes exactly the invitation whose hash is transaction-locally bound;
it does not expose other invitations or permit mutation. The raw capability is
sent only in the body of the fixed `POST /api/v1/invitations/inspect` and
`POST /api/v1/invitations/accept` routes, never in a URL path. Acceptance then
opens a normal tenant transaction, locks the Organization authority boundary
before the invitation, serializes identity creation by normalized email, and
atomically creates or reactivates one Membership, consumes the invitation, and
appends its allowed audit event.

Serialize lifecycle, invitation acceptance, and every Organization
administration mutation with one transaction advisory lock. After obtaining
that lock, revalidate the Organization and actor. Membership mutations also
protect the last active organization_admin before any state change. Invitation
create and resend acquire their normalized-email advisory lock before any
invitation row lock, giving all competing paths one lock order.

A malformed Organization path segment is returned as a safe 404 before tenant
binding. It does not identify an Organization and therefore cannot be appended
to an Organization-scoped audit stream; valid Organization identifiers enter
the audited mutation seam before authorization or body validation.

## Consequences

- A bearer invitation token can inspect only its own safe invitation view.
- Routine URL, proxy, and access logs do not receive the raw invitation token.
- Token reuse and concurrent acceptance have one winner.
- Acceptance business state and its allowed audit event commit or roll back
  together; rejected/failed evidence uses a later tenant transaction.
- Password hashing remains outside database transactions and uses the existing
  bounded password-work pool.
- Lifecycle and administration mutation throughput is serialized per
  Organization, which is acceptable for low-volume administration and makes
  the authority invariant explicit.
