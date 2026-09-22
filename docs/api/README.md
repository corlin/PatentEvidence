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

Password KDF work is dispatched to worker threads. Login verifies an unlocked
identity snapshot, then locks and rechecks its password hash, security version,
and status before rotating or issuing a session; concurrent identity changes
therefore fail with the generic credential error without holding a row lock
during Argon2 verification.

The API owns a dedicated bounded password-work executor. Login applies both
socket-peer-IP and SHA-256-derived email limits before reserving capacity; a
full worker/queue budget returns the same temporary-unavailability response for
known and unknown identities. Snapshot and finalization transactions are
separate, so no database connection is held while Argon2 runs or waits in the
bounded queue. Once submitted, the executor future owns the reserved capacity
until it completes or is cancelled before execution; cancelling the request
coroutine cannot admit replacement work while its worker is still running.

Password-reset confirmation applies an aggregate socket-peer-IP limit and
reserves password-work capacity before checking the token. With capacity
available, it validates unused/unexpired token and active identity snapshots
before hashing, closes that transaction for KDF, then locks and rechecks token
identity plus identity security version before applying the password change.
Invalid tokens therefore schedule no Argon2, while capacity and race failures
do not disclose token validity.

## Pre-assessment versions

The pre-assessment stage is exposed under
`/api/v1/organizations/{organization_id}/cases/{case_id}/assessments`. Every
route is either a read or an append: `POST` creates a version or appends a
review decision, `GET` lists versions, reads one version, and derives its
status. No route rewrites or deletes a version.

Creating a version runs the deterministic gates once and freezes the resulting
package — candidate findings, blocking gaps, flags and the three-step
scaffolding — together with the rules version, the prompt versions and a
SHA-256 over the canonical payload. Submitting and deciding append decision
records; status is always derived from that append-only decision stream rather
than stored on the version row, so an approved version keeps pointing at the
exact bytes that were approved.

### Disclosure rule

An assessment version never carries a patentability conclusion. The domain
layer emits candidate findings and the gaps that must still be closed, and the
HTTP layer must not invent a conclusion on top of them. Every response repeats
`requires_human_confirmation` and a `disclaimer` stating that the package is
candidate output rather than legal advice, so a caller cannot read one as a
confirmed opinion by accident. Approving a version that still has open
blockers requires the reviewer to set `accepts_insufficient_evidence`
explicitly and record a reason; the state machine rejects the transition
otherwise, and any attempt to decide on a version already in a terminal state
is refused — a revision is a new version number.

### Assembling input from existing case data

`POST .../assessments/from-case` builds the assessment input from data the
case already holds — the confirmed comparison matrix supplies the feature
cells and their citations, search candidates supply the documents, and search
jobs supply the source runs — then freezes the result as a new version.

Two facts cannot be inferred and must be recorded first, under
`.../assessment-input`: the subject application's own filing date, priority
claims and application type, and each candidate document's filing/priority
dates plus whether its source was verified. A publication date is not a filing
date, and a search hit is not a verified source, so neither is guessed. These
profiles are mutable input rather than approval records; editing one can only
affect the next version, never one already written.

Assembly never fills defaults over missing data. Missing the subject filing
date or any comparison cell refuses the request outright — a date gate with no
baseline is meaningless, and producing a version would only mislead. Missing
candidate dates, unverified sources and unverified citations are reported in
`gaps` and merged into the version's blockers, where they block any
conclusion. In particular, citations are always assembled as unverified: no
persisted field records whether a quote was located verbatim in the source,
and a confirmed comparison matrix means a human reviewed the chart, not that
each quote was traced. Mapping one onto the other would overstate the
evidence, so the gap stays visible and blocks instead.
