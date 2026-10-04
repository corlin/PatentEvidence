"""Store public patent legal-status observations and assessments (ADR 0006).

Revision ID: 0018_legal_status_store
Revises: 0017_source_doc_findings

Legal status of a published patent is public and identical for every
organization, so it lives in global tables without ``organization_id`` and
without per-organization RLS. Which organization looks at which patent is
sensitive and must never be stored here; tenant references belong in
tenant-scoped tables.

Both tables are append-only for runtime roles (no UPDATE/DELETE grants): a new
lookup or a new rules version adds rows and never rewrites history. Only the
worker writes; the API role can only read.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018_legal_status_store"
down_revision = "0017_source_doc_findings"
branch_labels = None
depends_on = None

SOURCES = ("uspto_odp", "epo_ops_inpadoc")
STATUSES = ("presumed_in_force", "lapsed", "expired", "undetermined")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "legal_status_source_records",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("publication_number", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        # Endpoint and parameters of the request, never credentials.
        sa.Column("request_ref", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        # The source's own data time (ODP lastIngestionDateTime); may be months old.
        sa.Column("source_data_as_of", sa.DateTime(timezone=True), nullable=True),
        # "not_found" is recorded too: it proves the lookup happened, not that the patent is dead.
        sa.Column("outcome", sa.String(16), nullable=False),
        # Only the fields the rules read; full responses go to object storage.
        sa.Column("extract", JSONB(), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=True),
        sa.Column("raw_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("raw_storage_key", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(_in("source", SOURCES), name="ck_legal_status_source_records_source"),
        sa.CheckConstraint("outcome IN ('found', 'not_found')", name="ck_legal_status_source_records_outcome"),
        sa.CheckConstraint(
            "(outcome = 'found' AND extract IS NOT NULL AND raw_sha256 IS NOT NULL)"
            " OR (outcome = 'not_found' AND extract IS NULL)",
            name="ck_legal_status_source_records_found_has_data",
        ),
        sa.CheckConstraint(
            "raw_sha256 IS NULL OR raw_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_legal_status_source_records_sha256",
        ),
    )
    op.create_index(
        "ix_legal_status_source_records_lookup",
        "legal_status_source_records",
        ["publication_number", "source", sa.text("retrieved_at DESC")],
    )

    op.create_table(
        "legal_status_assessments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("publication_number", sa.String(32), nullable=False),
        sa.Column("jurisdiction", sa.String(2), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("rules_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("term", JSONB(), nullable=True),
        sa.Column("countries", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("review_reasons", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # SHA-256 of the canonical assessment JSON, bound when an evidence snapshot is sealed.
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["legal_status_source_records.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("jurisdiction IN ('US', 'EP')", name="ck_legal_status_assessments_jurisdiction"),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_legal_status_assessments_status"),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_legal_status_assessments_sha256"
        ),
    )
    op.create_unique_constraint(
        "uq_legal_status_assessments_input",
        "legal_status_assessments",
        ["source_record_id", "as_of", "rules_version"],
    )
    op.create_index(
        "ix_legal_status_assessments_lookup",
        "legal_status_assessments",
        ["publication_number", sa.text("as_of DESC")],
    )

    for table in ("legal_status_source_records", "legal_status_assessments"):
        op.execute(f'GRANT SELECT, INSERT ON "{table}" TO patent_evidence_worker')
        op.execute(f'GRANT SELECT ON "{table}" TO patent_evidence_app')


def downgrade() -> None:
    op.drop_table("legal_status_assessments")
    op.drop_table("legal_status_source_records")
