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
it does not expose other invitations or permit mutation. Acceptance then opens a
normal tenant transaction, locks the invitation, serializes identity creation by
normalized email, and atomically creates or reactivates one Membership, consumes
the invitation, and appends its allowed audit event.

Serialize every role, suspension, reactivation, and removal mutation for an
Organization with a transaction advisory lock. After obtaining that lock,
revalidate the actor and protect the last active organization_admin before any
state change.

## Consequences

- A bearer invitation token can inspect only its own safe invitation view.
- Token reuse and concurrent acceptance have one winner.
- Acceptance business state and its allowed audit event commit or roll back
  together; rejected/failed evidence uses a later tenant transaction.
- Password hashing remains outside database transactions and uses the existing
  bounded password-work pool.
- Membership mutation throughput is serialized per Organization, which is
  acceptable for low-volume administration and makes the invariant explicit.
