"""Add feature set versions and claim features tables.

Revision ID: 0005_features_modeling
Revises: 0004_cases_documents
"""

import sqlalchemy as sa
from alembic import op
from helpers.tenancy import enable_force_rls

revision = "0005_features_modeling"
down_revision = "0004_cases_documents"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = (
    "feature_set_versions",
    "claim_features",
)


def upgrade() -> None:
    # 1. feature_set_versions
    op.create_table(
        "feature_set_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("summary", sa.String(512), nullable=True),
        sa.Column("confirmed_by_identity_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["feature_set_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "uq_feature_set_versions_case_ver",
        "feature_set_versions",
        ["case_id", "version_number"],
        unique=True,
    )
    op.create_index(
        "ix_feature_set_versions_case_status",
        "feature_set_versions",
        ["case_id", "status"],
    )

    # 2. claim_features
    op.create_table(
        "claim_features",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("feature_set_version_id", sa.Uuid(), nullable=False),
        sa.Column("feature_code", sa.String(32), nullable=False),
        sa.Column("feature_type", sa.String(32), nullable=False, server_default="characterizing"),
        sa.Column("feature_statement", sa.Text(), nullable=False),
        sa.Column("source_paragraph_id", sa.String(64), nullable=True),
        sa.Column("citation_quote", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        "ix_claim_features_version_sort",
        "claim_features",
        ["feature_set_version_id", "sort_order"],
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
