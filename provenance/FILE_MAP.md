# Derived file map

No source implementation files have been copied into this P0 scaffold.

The committed `sources.lock.json` is an accepted governance record copied from
the product-specification deliverable; it is not a derivative source file.
Add one row below before introducing any substantive derivative file.

| Destination | Source repository/path@commit | Modification summary | Owner | Tests |
| --- | --- | --- | --- | --- |
| `apps/api/migrations/helpers/tenancy.py` | `PatentQ/apps/api/migrations/helpers/tenancy.py@eb63654464e51fa0d68027679c6626fb2a0c608b` | Adapted FORCE RLS and composite-key helper concepts for PatentEvidence role names and migration-owner maintenance. | PatentEvidence | `./scripts/test-postgres.sh` |
| `apps/api/migrations/versions/0001_identity_tenancy.py` | `PatentQ/apps/api/migrations/versions/0001_database_roles.py`, `0002_identity_and_tenancy.py@eb63654464e51fa0d68027679c6626fb2a0c608b` | Re-derived a smaller P0-02 schema, grants, role preflight, tenant policies, and append-only audit boundary. | PatentEvidence | `./scripts/test-postgres.sh` |
| `apps/api/src/patent_evidence_api/core/database.py` | `PatentQ/apps/api/src/patentq/core/database.py@eb63654464e51fa0d68027679c6626fb2a0c608b` | Extended the async transaction wrapper with tenant, actor, and request context binding plus a repository guard. | PatentEvidence | `apps/api/tests/integration/test_database_context.py` |
| `apps/api/tests/integration/test_database_roles_and_rls.py` | `PatentQ/apps/api/tests/integration/test_database_roles_and_rls.py@eb63654464e51fa0d68027679c6626fb2a0c608b` | Re-authored real-role RLS probes for PatentEvidence schema, credential-column denial, provisioning, and audit immutability. | PatentEvidence | Self-testing via `./scripts/test-postgres.sh` |
