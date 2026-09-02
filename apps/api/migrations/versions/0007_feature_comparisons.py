"""Add comparison matrices and claim feature comparisons tables.

Revision ID: 0007_feature_comparisons
Revises: 0006_search_and_candidates
"""

import sqlalchemy as sa
from alembic import op

from helpers.tenancy import enable_force_rls

revision = "0007_feature_comparisons"
down_revision = "0006_search_and_candidates"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = (
    "comparison_matrices",
    "claim_feature_comparisons",
)


def upgrade() -> None:
    # 1. comparison_matrices
    op.create_table(
        "comparison_matrices",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("feature_set_version_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(256), nullable=False, server_default="权利要求特征比对表"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("summary", sa.Text(), nullable=True),
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
            ["feature_set_version_id"], ["feature_set_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_unique_constraint(
        "uq_comparison_matrices_case_fsv",
        "comparison_matrices",
        ["case_id", "feature_set_version_id"],
    )
    op.create_index(
        "ix_comparison_matrices_case_status",
        "comparison_matrices",
        ["case_id", "status"],
    )

    # 2. claim_feature_comparisons
    op.create_table(
        "claim_feature_comparisons",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("matrix_id", sa.Uuid(), nullable=False),
        sa.Column("claim_feature_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("judgment", sa.String(32), nullable=False, server_default="different"),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("citation_location", sa.String(128), nullable=True),
        sa.Column("citation_quote", sa.Text(), nullable=True),
        sa.Column("reasoning_analysis", sa.Text(), nullable=True),
        sa.Column("is_manually_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["matrix_id"], ["comparison_matrices.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["claim_feature_id"], ["claim_features.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["search_candidates.id"], ondelete="CASCADE"
        ),
    )
    op.create_unique_constraint(
        "uq_claim_feature_comparisons_matrix_feature_cand",
        "claim_feature_comparisons",
        ["matrix_id", "claim_feature_id", "candidate_id"],
    )
    op.create_index(
        "ix_claim_feature_comparisons_matrix_judgment",
        "claim_feature_comparisons",
        ["matrix_id", "judgment"],
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
