"""Add case drawings asset table for patent figures and drawings.

Revision ID: 0009_case_drawings
Revises: 0008_evidence_snapshots_reports
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0009_case_drawings"
down_revision = "0008_evidence_snapshots_reports"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = (
    "case_drawings",
)


def upgrade() -> None:
    op.create_table(
        "case_drawings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=True),
        sa.Column("document_version_id", sa.Uuid(), nullable=True),
        sa.Column("figure_label", sa.String(64), nullable=False, server_default="附图"),
        sa.Column("figure_title", sa.String(256), nullable=False, server_default=""),
        sa.Column("reference_marks", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False, server_default="image/png"),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_manually_added", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_case_drawings_case_order",
        "case_drawings",
        ["case_id", "order_index"],
    )

    for table in NEW_TENANT_TABLES:
        for role in RUNTIME_ROLES:
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO {role}'
            )
        enable_force_rls(table)

    op.execute(
        """CREATE POLICY case_drawings_worker_policy ON case_drawings
        TO patent_evidence_worker USING (true) WITH CHECK (true)"""
    )


def downgrade() -> None:
    for table in reversed(NEW_TENANT_TABLES):
        op.drop_table(table)
