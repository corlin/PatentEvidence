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
- **Organization Invitation** — a 72-hour, single-use capability bound to one Organization, normalized email, and fixed Organization Role. Only its hash is persisted.
- **Organization Role** — exactly one of organization_admin, patent_agent, or reviewer; platform_admin is never an Organization Role.
- **Membership Lifecycle** — the Organization Membership states active, suspended, and removed. Removed memberships are retained as history and may only become active through a new invitation acceptance.
- **Last Active Administrator Invariant** — every Organization must retain at least one active organization_admin across role, suspension, and removal races.

## Evidence

- **Platform Audit Event** — immutable, secret-safe evidence of an attempted platform-wide privileged action, whether allowed, denied, or failed.
- **Organization Audit Event** — immutable, tenant-scoped, secret-safe evidence of an attempted Organization mutation, whether allowed, denied, or failed.
- **Request Correlation ID** — a safe identifier connecting one attempted action to its Platform Audit Event.

## FTO and Design-Around (Stage-Gate Evidence)

These are working definitions for product and engineering vocabulary, not legal
advice. Jurisdiction-specific judgment rules are defined in rule packs and must
be approved by qualified professionals (ADR 0004). Most of these concepts are
not implemented yet; see the status labels in `README.md`.

- **FTO (Freedom to Operate)** — a structured risk analysis assessing whether making, using, offering to sell, selling, or importing an enterprise product infringes valid patent claims in target jurisdictions (China, US, Europe/UPC/Germany).
- **Design-Around (规避设计)** — an intentional engineering redesign intended to ensure that at least one technical feature of each asserted claim is not present in the product, either literally or by an equivalent, assessed under the all-elements rule (全面覆盖原则) and the doctrine of equivalents (等同原则) as applied in the relevant jurisdiction. It reduces infringement risk; it does not by itself establish non-infringement.
- **Closed-Loop Auto-Validation (闭环反向验真)** — automated re-execution of the comparison engine that checks a proposed design-around against the competitor's claim tree (independent and dependent claims) and the patent family before the suggestion is shown, to flag whether it may still read on any of them. It is a screening step that lowers the chance of a missed claim. It cannot guarantee freedom from infringement, and its result requires professional review.
- **Dual-Role Stage-Gate Pass (双角色门禁通行凭证)** — an immutable, cryptographically sealed clearance certificate produced after IP Counsel final approval of the Claim Chart and design-around, required for engineering projects to clear phase-gate milestones in PLM/ERP systems.
- **Dual-Track Trusted Timestamping (双轨可信时间戳存证)** — binding the hash of a sealed evidence snapshot both to a domestic trusted-timestamp or judicial preservation service (e.g., Tianping Chain, NTSC; provider not yet chosen) and to an international RFC 3161 TSA and/or public-blockchain anchor. It is intended to prove that the snapshot existed unchanged at a given time. Admissibility and evidentiary weight are decided by the tribunal in each proceeding.
- **Broken Element (特征断点)** — a technical feature of an asserted claim that the candidate design is assessed not to meet, either literally or by an equivalent (for example, the feature is absent, or is replaced by a structure or principle judged not equivalent). Infringement is assessed for the claim as a whole; a broken element is the basis for that claim-level conclusion, not a conclusion in itself.

