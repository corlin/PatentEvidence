"""Add assessment version review decisions (append-only).

Revision ID: 0014_assessment_version_reviews
Revises: 0013_assessment_versions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0014_assessment_version_reviews"
down_revision = "0013_assessment_versions"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

# 决策记录同样只追加：一次复核结论一旦写入即不可改，改判会产生新的一条决策。
NEW_TENANT_TABLES = ("assessment_version_reviews",)


def upgrade() -> None:
    op.create_table(
        "assessment_version_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("assessment_version_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reviewer_identity_id", sa.Uuid(), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("open_blockers", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "accepts_insufficient_evidence",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("decision_signature", sa.String(64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assessment_version_id"], ["assessment_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_assessment_version_reviews_version",
        "assessment_version_reviews",
        ["assessment_version_id", "decided_at"],
    )
    op.create_index(
        "ix_assessment_version_reviews_case_decision",
        "assessment_version_reviews",
        ["case_id", "decision"],
    )

    for table in NEW_TENANT_TABLES:
        for role in RUNTIME_ROLES:
            op.execute(f'GRANT SELECT, INSERT ON "{table}" TO {role}')
        enable_force_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TENANT_TABLES):
        op.drop_table(table)
