"""Freeze pre-assessment input profiles alongside each assessment version.

Revision ID: 0016_assessment_input_snapshots
Revises: 0015_assessment_input_profiles

The input profiles (`case_application_profiles`, `candidate_document_profiles`) are
*mutable* — a practitioner may correct a filing date after a version was already
sealed. That is correct (a corrected date only affects the *next* version), but it
means the live tables can no longer tell you what the inputs were when a given
version was produced. Without that, a version diff cannot attribute a conclusion
change to an input change; it could only guess, which would be fabrication.

This table freezes, per version, the exact application profile and candidate
profiles that drove that version. It is append-only (the version is immutable, so
its input record is too): runtime roles get SELECT and INSERT only, never
UPDATE/DELETE.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0016_assessment_input_snapshots"
down_revision = "0015_assessment_input_profiles"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = ("assessment_input_snapshots",)


def upgrade() -> None:
    op.create_table(
        "assessment_input_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        # 绑定到确切版本：改写版本是被禁止的，因此它的输入记录也是冻结的。
        sa.Column("assessment_version_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        # 冻结时的本案申请信息：filing_date / application_type / priority_claims。
        sa.Column("application_profile", JSONB(), nullable=True),
        # 冻结时的各对比文件档案：publication_number / filing_date / priority_date /
        # filed_in_china / source_verified。
        sa.Column("candidate_profiles", JSONB(), nullable=True),
        sa.Column("rules_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
    )
    op.create_unique_constraint(
        "uq_assessment_input_snapshots_version",
        "assessment_input_snapshots",
        ["assessment_version_id"],
    )
    op.create_unique_constraint(
        "uq_assessment_input_snapshots_case_version",
        "assessment_input_snapshots",
        ["case_id", "version_number"],
    )
    op.create_index(
        "ix_assessment_input_snapshots_case",
        "assessment_input_snapshots",
        ["case_id", "version_number"],
    )

    for table in NEW_TENANT_TABLES:
        for role in RUNTIME_ROLES:
            op.execute(f'GRANT SELECT, INSERT ON "{table}" TO {role}')
        enable_force_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TENANT_TABLES):
        op.drop_table(table)
