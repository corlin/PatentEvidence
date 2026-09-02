"""Add search strategies, search jobs, search candidates, and candidate triage records tables.

Revision ID: 0006_search_and_candidates
Revises: 0005_features_modeling
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0006_search_and_candidates"
down_revision = "0005_features_modeling"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = (
    "search_strategies",
    "search_jobs",
    "search_candidates",
    "candidate_triage_records",
)


def upgrade() -> None:
    # 1. search_strategies
    op.create_table(
        "search_strategies",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("feature_set_version_id", sa.Uuid(), nullable=False),
        sa.Column("keywords_matrix", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ipc_classes", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("boolean_query_cnipr", sa.Text(), nullable=False),
        sa.Column("boolean_query_standard", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["feature_set_version_id"], ["feature_set_versions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_search_strategies_case_created",
        "search_strategies",
        ["case_id", "created_at"],
    )

    # 2. search_jobs
    op.create_table(
        "search_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["search_strategies.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_search_jobs_case_status",
        "search_jobs",
        ["case_id", "status"],
    )

    # 3. search_candidates
    op.create_table(
        "search_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("publication_number", sa.String(128), nullable=False),
        sa.Column("publication_number_normalized", sa.String(128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False, server_default=""),
        sa.Column("publication_date", sa.String(32), nullable=True),
        sa.Column("applicant", sa.Text(), nullable=True),
        sa.Column("ipc_classification", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("raw_metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
    )
    op.create_unique_constraint(
        "uq_search_candidates_tenant_case_pub",
        "search_candidates",
        ["organization_id", "case_id", "publication_number_normalized"],
    )
    op.create_index(
        "ix_search_candidates_case_score",
        "search_candidates",
        ["case_id", "relevance_score"],
    )

    # 4. candidate_triage_records
    op.create_table(
        "candidate_triage_records",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("triage_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("exclusion_reason", sa.String(128), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("triaged_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["search_candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["triaged_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_unique_constraint(
        "uq_candidate_triage_records_candidate",
        "candidate_triage_records",
        ["candidate_id"],
    )
    op.create_index(
        "ix_candidate_triage_case_status",
        "candidate_triage_records",
        ["case_id", "triage_status"],
    )

    # Grant table permissions & enable forced RLS
    for table in NEW_TENANT_TABLES:
        for role in RUNTIME_ROLES:
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO {role}'
            )
        enable_force_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TENANT_TABLES):
        op.drop_table(table)
