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

- **FTO (Freedom to Operate)** — a structured risk analysis assessing whether making, using, offering to sell, selling, or importing an enterprise product infringes valid patent claims in target jurisdictions (China, US, Europe/UPC/Germany).
- **Design-Around (规避设计)** — an intentional engineering redesign breaking at least one essential technical feature of an asserted independent claim under the All-Elements Rule (全面覆盖原则) while eliminating risks under the Doctrine of Equivalents (等同原则).
- **Closed-Loop Auto-Validation (闭环反向验真)** — automated re-execution of the comparison engine that tests a proposed design-around against the competitor's full claim tree (including all dependent claims) and family patent thicket to guarantee zero secondary infringement before presenting suggestions to engineers.
- **Dual-Role Stage-Gate Pass (双角色门禁通行凭证)** — an immutable, cryptographically sealed clearance certificate produced after IP Counsel final approval of the Claim Chart and design-around, required for engineering projects to clear phase-gate milestones in PLM/ERP systems.
- **Dual-Track Trusted Timestamping (双轨可信时间戳存证)** — the cryptographic anchor binding a sealed evidence snapshot simultaneously to domestic judicial preservation chains (e.g., Tianping Chain / NTSC) and international RFC 3161 TSA / public blockchain state hashes for court admissibility in domestic litigation, cross-border disputes, and US ITC Section 337 investigations.
- **Broken Element (特征断点)** — a technical element in an asserted claim where the candidate engineering design is determined to be non-infringing (missing, structurally differentiated, or operating on fundamentally different physical principles).

