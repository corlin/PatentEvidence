"""Add pre-assessment input profiles (subject application + candidate dates).

Revision ID: 0015_assessment_input_profiles
Revises: 0014_assessment_version_reviews

The deterministic gates need two facts that no existing table carries: the
subject application's own filing/priority dates, and each candidate document's
filing/priority dates plus whether its source was actually verified. Neither
can be inferred — a publication date is not a filing date, and a search hit is
not a verified source.

These tables hold human-entered input, not approval records, so they are
mutable. That does not weaken assessment provenance: a version freezes its
package and SHA-256 at creation time, so editing an input later can only
affect the *next* version, never one already written or approved.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0015_assessment_input_profiles"
down_revision = "0014_assessment_version_reviews"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)

NEW_TENANT_TABLES = (
    "case_application_profiles",
    "candidate_document_profiles",
)


def upgrade() -> None:
    op.create_table(
        "case_application_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("application_type", sa.String(32), nullable=False, server_default="invention"),
        # 每项优先权主张：claim_id / priority_date / country / first_application /
        # same_subject / proof_verified / covers。空数组表示无优先权主张。
        sa.Column("priority_claims", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recorded_by_identity_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recorded_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_unique_constraint(
        "uq_case_application_profiles_case",
        "case_application_profiles",
        ["case_id"],
    )

    op.create_table(
        "candidate_document_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("priority_date", sa.Date(), nullable=True),
        sa.Column("filed_in_china", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verified_by_identity_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["search_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["verified_by_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
    )
    op.create_unique_constraint(
        "uq_candidate_document_profiles_candidate",
        "candidate_document_profiles",
        ["case_id", "candidate_id"],
    )
    op.create_index(
        "ix_candidate_document_profiles_case",
        "candidate_document_profiles",
        ["case_id"],
    )

    for table in NEW_TENANT_TABLES:
        for role in RUNTIME_ROLES:
            op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO {role}')
        enable_force_rls(table)


def downgrade() -> None:
    for table in reversed(NEW_TENANT_TABLES):
        op.drop_table(table)
