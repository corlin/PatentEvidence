"""Add cases, source documents, document versions, and parse runs.

Revision ID: 0004_cases_documents
Revises: 0003_organization_administration
"""

import sqlalchemy as sa
from alembic import op
from helpers.tenancy import enable_force_rls

revision = "0004_cases_documents"
down_revision = "0003_organization_administration"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = (
    "cases",
    "source_documents",
    "document_versions",
    "parse_runs",
)


def upgrade() -> None:
    # 1. cases
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_number", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("technical_field", sa.String(128), nullable=False),
        sa.Column("target_jurisdiction", sa.String(32), nullable=False, server_default="CN"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "uq_cases_org_case_number",
        "cases",
        ["organization_id", "case_number"],
        unique=True,
    )
    op.create_index(
        "ix_cases_org_created_at",
        "cases",
        ["organization_id", "created_at"],
    )

    # 2. source_documents
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_source_documents_case_id",
        "source_documents",
        ["case_id", "created_at"],
    )

    # 3. document_versions
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("parsed_text", sa.Text(), nullable=False),
        sa.Column("structure_json", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by_identity_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["document_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "uq_document_versions_case_ver",
        "document_versions",
        ["case_id", "version_number"],
        unique=True,
    )

    # 4. parse_runs
    op.create_table(
        "parse_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"], ["cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_parse_runs_status_created",
        "parse_runs",
        ["status", "created_at"],
    )

    # Grant table permissions
    for table in NEW_TENANT_TABLES:
        for role in RUNTIME_ROLES:
            op.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO {role}'
            )
        enable_force_rls(table)

    op.execute(
        """CREATE POLICY parse_runs_worker_policy ON parse_runs
        TO patent_evidence_worker USING (true) WITH CHECK (true)"""
    )
    op.execute(
        """CREATE POLICY source_documents_worker_policy ON source_documents
        FOR SELECT TO patent_evidence_worker USING (true)"""
    )
    op.execute(
        """CREATE POLICY document_versions_worker_policy ON document_versions
        TO patent_evidence_worker USING (true) WITH CHECK (true)"""
    )


def downgrade() -> None:
    for table in reversed(NEW_TENANT_TABLES):
        op.drop_table(table)
