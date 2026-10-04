"""US/EP patent corpus loads (ADR 0007, stage 1 of ADR 0005).

Revision ID: 0019_patent_corpus
Revises: 0018_legal_status_store

Public bibliographic data, shared by all organizations: global tables without
organization_id or tenant RLS (same pattern as ADR 0006). Each load is a new,
immutable batch, so an FTO analysis can always say which corpus it used.
Runtime roles: worker SELECT+INSERT, app SELECT; no UPDATE/DELETE.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0019_patent_corpus"
down_revision = "0018_legal_status_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patent_corpus_loads",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        # Jurisdictions, kinds, classification prefixes, margins and computed cutoffs.
        sa.Column("scope", JSONB(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("source_table_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("bytes_billed", sa.BigInteger(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("query_sha256 ~ '^[0-9a-f]{64}$'", name="ck_patent_corpus_loads_sha256"),
        sa.CheckConstraint("row_count >= 0", name="ck_patent_corpus_loads_row_count"),
    )

    op.create_table(
        "patent_corpus_members",
        sa.Column("load_id", sa.Uuid(), nullable=False),
        sa.Column("publication_number", sa.String(32), nullable=False),
        sa.Column("jurisdiction", sa.String(2), nullable=False),
        sa.Column("kind", sa.String(4), nullable=False),
        # Google Patents application number: NOT the USPTO application number. Grouping only.
        sa.Column("application_number", sa.String(32), nullable=True),
        sa.Column("family_id", sa.String(32), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("grant_date", sa.Date(), nullable=True),
        sa.Column("priority_date", sa.Date(), nullable=True),
        sa.Column("cpc_codes", ARRAY(sa.Text()), nullable=False),
        sa.Column("ipc_codes", ARRAY(sa.Text()), nullable=False),
        sa.Column("assignees_original", ARRAY(sa.Text()), nullable=False),
        sa.Column("assignees_harmonized", ARRAY(sa.Text()), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=True),
        sa.Column("title_original", sa.Text(), nullable=True),
        sa.Column("scope_match", sa.String(8), nullable=False),
        sa.PrimaryKeyConstraint("load_id", "publication_number"),
        sa.ForeignKeyConstraint(["load_id"], ["patent_corpus_loads.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("jurisdiction IN ('US', 'EP')", name="ck_patent_corpus_members_jurisdiction"),
        sa.CheckConstraint("scope_match IN ('cpc', 'ipc', 'both')", name="ck_patent_corpus_members_scope"),
    )
    op.create_index(
        "ix_patent_corpus_members_application",
        "patent_corpus_members",
        ["load_id", "jurisdiction", "application_number"],
    )
    op.create_index("ix_patent_corpus_members_family", "patent_corpus_members", ["load_id", "family_id"])

    for table in ("patent_corpus_loads", "patent_corpus_members"):
        op.execute(f'GRANT SELECT, INSERT ON "{table}" TO patent_evidence_worker')
        op.execute(f'GRANT SELECT ON "{table}" TO patent_evidence_app')


def downgrade() -> None:
    op.drop_table("patent_corpus_members")
    op.drop_table("patent_corpus_loads")
