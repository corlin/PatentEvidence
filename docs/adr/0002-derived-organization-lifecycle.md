# ADR 0002: Derive organization expiry

- Status: Accepted
- Date: 2026-09-01

## Context

An Organization has an operator-controlled status and an optional expiry time. Persisting an additional expired status would require clocks or background work to keep stored state synchronized. Updating the Quota Plan whenever the Organization changes lifecycle would duplicate the same state in two records.

## Decision

Persist only operator-controlled Organization states: active and suspended. Derive the effective Organization Lifecycle at read and authorization time:

1. An elapsed expiry means expired.
2. Otherwise, a persisted suspension means suspended.
3. Otherwise, the Organization is active.

The Quota Plan keeps its own allocation status. Its effective availability inherits expired or suspended from the Organization before considering its own status. Suspending or reactivating an Organization does not rewrite the Quota Plan.

## Consequences

- Expiry becomes effective without a scheduler.
- Read, authorization, and mutation paths must use the same lifecycle rule.
- Clearing or extending expiry can make an otherwise active Organization active again.
- Tests need a controlled clock and must cover Organization and Quota Plan projections together.
