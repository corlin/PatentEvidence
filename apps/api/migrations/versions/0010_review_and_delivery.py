"""Add review submissions, review decisions, and delivery records tables.

Revision ID: 0010_review_and_delivery
Revises: 0009_case_drawings
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0010_review_and_delivery"
down_revision = "0009_case_drawings"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = (
    "review_submissions",
    "review_decisions",
    "delivery_records",
)


def upgrade() -> None:
    # 1. review_submissions
    op.create_table(
        "review_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("evidence_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("submitter_identity_id", sa.Uuid(), nullable=True),
        sa.Column("submitter_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_snapshot_id"], ["evidence_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["analysis_reports.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["submitter_identity_id"], ["global_identities.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_review_submissions_case_round",
        "review_submissions",
        ["case_id", "round_number"],
    )

    # 2. review_decisions
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("review_submission_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_identity_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("overall_comments", sa.Text(), nullable=False, server_default=""),
        sa.Column("itemized_feedback", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_self_audit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("decision_signature", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["review_submission_id"], ["review_submissions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_identity_id"], ["global_identities.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_review_decisions_submission",
        "review_decisions",
        ["review_submission_id"],
    )

    # 3. delivery_records
    op.create_table(
        "delivery_records",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("review_submission_id", sa.Uuid(), nullable=True),
        sa.Column("final_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("final_report_id", sa.Uuid(), nullable=True),
        sa.Column("delivered_by_identity_id", sa.Uuid(), nullable=True),
        sa.Column("client_recipient", sa.String(256), nullable=False, server_default=""),
        sa.Column("download_token", sa.String(128), nullable=False, unique=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["review_submission_id"], ["review_submissions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["final_snapshot_id"], ["evidence_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["final_report_id"], ["analysis_reports.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["delivered_by_identity_id"], ["global_identities.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_delivery_records_case",
        "delivery_records",
        ["case_id"],
    )

    for table in NEW_TENANT_TABLES:
        for role in RUNTIME_ROLES:
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO {role}'
            )
        enable_force_rls(table)
        op.execute(
            f"""CREATE POLICY {table}_worker_policy ON "{table}"
            TO patent_evidence_worker USING (true) WITH CHECK (true)"""
        )


def downgrade() -> None:
    for table in reversed(NEW_TENANT_TABLES):
        op.drop_table(table)
