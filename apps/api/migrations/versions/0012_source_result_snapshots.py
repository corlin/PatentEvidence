"""Add append-only canonical provider-record snapshots.

Revision ID: 0012_source_result_snapshots
Revises: 0011_self_identity_visibility
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0012_source_result_snapshots"
down_revision = "0011_self_identity_visibility"
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_worker",
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_cases_org_case_id",
        "cases",
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_search_jobs_org_case_job_id",
        "search_jobs",
        ["organization_id", "case_id", "id"],
    )
    op.create_unique_constraint(
        "uq_search_candidates_org_case_candidate_id",
        "search_candidates",
        ["organization_id", "case_id", "id"],
    )
    op.create_table(
        "source_result_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("search_job_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_identifier", sa.String(256), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "case_id"],
            ["cases.organization_id", "cases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "case_id", "search_job_id"],
            ["search_jobs.organization_id", "search_jobs.case_id", "search_jobs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "case_id", "candidate_id"],
            [
                "search_candidates.organization_id",
                "search_candidates.case_id",
                "search_candidates.id",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "payload_sha256 = encode(sha256(convert_to(payload::text, 'UTF8')), 'hex')",
            name="ck_source_result_snapshots_sha256",
        ),
    )
    op.create_index(
        "ix_source_result_snapshots_candidate_retrieved",
        "source_result_snapshots",
        ["candidate_id", "retrieved_at"],
    )
    op.create_index(
        "ix_source_result_snapshots_job",
        "source_result_snapshots",
        ["search_job_id"],
    )

    enable_force_rls("source_result_snapshots")
    for role in RUNTIME_ROLES:
        op.execute(
            f"GRANT SELECT, INSERT ON source_result_snapshots TO {role}"
        )


def downgrade() -> None:
    op.drop_table("source_result_snapshots")
    op.drop_constraint(
        "uq_search_candidates_org_case_candidate_id",
        "search_candidates",
        type_="unique",
    )
    op.drop_constraint(
        "uq_search_jobs_org_case_job_id",
        "search_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "uq_cases_org_case_id",
        "cases",
        type_="unique",
    )
