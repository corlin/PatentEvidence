"""Store fetched claim texts (ADR 0009).

Revision ID: 0020_claim_documents
Revises: 0019_patent_corpus

Public claim text, shared by all organizations: global, append-only table
(ADR 0006 pattern). Runtime roles: worker SELECT+INSERT, app SELECT.
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_claim_documents"
down_revision = "0019_patent_corpus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patent_claim_documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("publication_number", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("request_ref", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        # US: creation time of the split grant XML file. Not a data date.
        sa.Column("source_file_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        # What the parser reads: US <claims> element; EP OPS claims JSON.
        sa.Column("claims_text", sa.Text(), nullable=True),
        # "as_granted" (US grant XML) or "as_published" (a specific EP publication).
        sa.Column("text_represents", sa.String(16), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=True),
        sa.Column("raw_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("raw_storage_key", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('uspto_grant_xml', 'epo_ops_claims')", name="ck_patent_claim_documents_source"),
        sa.CheckConstraint("outcome IN ('found', 'not_found')", name="ck_patent_claim_documents_outcome"),
        sa.CheckConstraint(
            "(outcome = 'found' AND claims_text IS NOT NULL AND raw_sha256 IS NOT NULL AND text_represents IS NOT NULL)"
            " OR (outcome = 'not_found' AND claims_text IS NULL)",
            name="ck_patent_claim_documents_found_has_text",
        ),
        sa.CheckConstraint(
            "text_represents IS NULL OR text_represents IN ('as_granted', 'as_published')",
            name="ck_patent_claim_documents_represents",
        ),
        sa.CheckConstraint(
            "raw_sha256 IS NULL OR raw_sha256 ~ '^[0-9a-f]{64}$'", name="ck_patent_claim_documents_sha256"
        ),
    )
    op.create_index(
        "ix_patent_claim_documents_lookup",
        "patent_claim_documents",
        ["publication_number", "source", sa.text("retrieved_at DESC")],
    )
    op.execute('GRANT SELECT, INSERT ON "patent_claim_documents" TO patent_evidence_worker')
    op.execute('GRANT SELECT ON "patent_claim_documents" TO patent_evidence_app')


def downgrade() -> None:
    op.drop_table("patent_claim_documents")
