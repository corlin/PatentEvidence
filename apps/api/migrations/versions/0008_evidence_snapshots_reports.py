"""Add evidence snapshots and analysis reports tables.

Revision ID: 0008_evidence_snapshots_reports
Revises: 0007_feature_comparisons
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0008_evidence_snapshots_reports"
down_revision = "0007_feature_comparisons"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = (
    "evidence_snapshots",
    "analysis_reports",
)


def upgrade() -> None:
    # 1. evidence_snapshots
    op.create_table(
        "evidence_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_number", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="sealed"),
        sa.Column("root_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sealed_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sealed_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_unique_constraint(
        "uq_evidence_snapshots_tenant_case_num",
        "evidence_snapshots",
        ["organization_id", "case_id", "snapshot_number"],
    )
    op.create_index(
        "ix_evidence_snapshots_case_sealed",
        "evidence_snapshots",
        ["case_id", "sealed_at"],
    )

    # 2. analysis_reports
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("report_title", sa.String(256), nullable=False),
        sa.Column("format", sa.String(32), nullable=False, server_default="markdown"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generated_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["evidence_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_analysis_reports_case_created",
        "analysis_reports",
        ["case_id", "created_at"],
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
