"""Add pre-assessment version snapshots (append-only).

Revision ID: 0013_assessment_versions
Revises: 0012_source_result_snapshots
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0013_assessment_versions"
down_revision = "0012_source_result_snapshots"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

# 评估版本是不可变快照：运行时角色只有 SELECT / INSERT，没有 UPDATE / DELETE。
# 修订即新增版本，已落库的评估包不得被改写。
NEW_TENANT_TABLES = ("assessment_versions",)


def upgrade() -> None:
    op.create_table(
        "assessment_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("rules_version", sa.String(64), nullable=False),
        sa.Column("prompt_versions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("blockers", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("flags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "requires_human_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by_identity_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_unique_constraint(
        "uq_assessment_versions_case_version",
        "assessment_versions",
        ["case_id", "version_number"],
    )
    op.create_index(
        "ix_assessment_versions_case_created",
        "assessment_versions",
        ["case_id", "created_at"],
    )

    for table in NEW_TENANT_TABLES:
        for role in RUNTIME_ROLES:
            op.execute(f'GRANT SELECT, INSERT ON "{table}" TO {role}')
        enable_force_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TENANT_TABLES):
        op.drop_table(table)
