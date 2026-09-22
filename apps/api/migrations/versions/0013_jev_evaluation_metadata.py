"""Persist evidence-gated Jev evaluation metadata.

Revision ID: 0013_jev_evaluation_metadata
Revises: 0012_source_result_snapshots
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013_jev_evaluation_metadata"
down_revision = "0012_source_result_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "claim_feature_comparisons",
        sa.Column("evidence_status", sa.String(32), nullable=False, server_default="insufficient"),
    )
    op.add_column(
        "claim_feature_comparisons",
        sa.Column("evaluation_source", sa.String(32), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "claim_feature_comparisons",
        sa.Column("evaluation_metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_check_constraint(
        "ck_claim_feature_comparisons_judgment",
        "claim_feature_comparisons",
        "judgment IN ('identical', 'equivalent', 'different', 'insufficient_evidence')",
    )
    op.create_check_constraint(
        "ck_claim_feature_comparisons_evidence_status",
        "claim_feature_comparisons",
        "evidence_status IN ('verified', 'abstract_only', 'missing_source_text', 'unverified_anchor', 'evaluation_failed', 'insufficient')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_claim_feature_comparisons_evidence_status", "claim_feature_comparisons", type_="check")
    op.drop_constraint("ck_claim_feature_comparisons_judgment", "claim_feature_comparisons", type_="check")
    op.drop_column("claim_feature_comparisons", "evaluation_metadata")
    op.drop_column("claim_feature_comparisons", "evaluation_source")
    op.drop_column("claim_feature_comparisons", "evidence_status")
