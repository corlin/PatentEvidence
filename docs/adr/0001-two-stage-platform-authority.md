# ADR 0001: Preserve two-stage platform authority

- Status: Accepted
- Date: 2026-09-01

## Context

A browser session is visible to the restricted application database role through token-hash RLS. Platform-wide mutations require a separate restricted platform role. Giving either role the other's data access would weaken least privilege, while repeating the orchestration in every route causes authorization and audit behavior to drift.

## Decision

Every platform-wide privileged operation uses two sequential transactions:

1. The application role resolves the opaque session, validates the current identity security version, and requires recent MFA.
2. After that transaction closes, the platform role re-derives the current Platform Operator Grant and performs the authorized read or mutation.

The orchestration may be concentrated behind one module interface, but the two roles, transactions, and authorization checks remain explicit inside its implementation. Rejected mutation attempts are recorded independently so their audit evidence survives rollback of the attempted mutation.

## Consequences

- Platform routes cannot read session credentials with the platform role.
- Application routes cannot provision organizations with the application role.
- A privileged request pays for two short transactions.
- Tests must prove both restricted roles and the handoff between them.
