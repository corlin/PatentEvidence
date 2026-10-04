"""FTO claim charts: claim snapshots, claim-feature confirmation, manual findings (ADR 0011).

Revision ID: 0022_fto_charts
Revises: 0021_product_features

Tenant data (the customer's product analysis): FORCE RLS. Charts and
findings are append-only; claim-feature text is a frozen snapshot and only
the confirmation (unconfirmed -> confirmed, once) may change, enforced by a
trigger.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from helpers.tenancy import enable_force_rls

revision = "0022_fto_charts"
down_revision = "0021_product_features"
branch_labels = None
depends_on = None

RUNTIME_ROLES = ("patent_evidence_app", "patent_evidence_worker")
TABLES = ("fto_charts", "fto_chart_claim_features", "fto_feature_findings")
FINDINGS = ("literally_present", "present_by_equivalent", "absent", "undetermined")


def upgrade() -> None:
    op.create_table(
        "fto_charts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("publication_number", sa.String(32), nullable=False),
        sa.Column("claim_document_id", sa.Uuid(), nullable=False),
        sa.Column("claims_text_sha256", sa.String(64), nullable=False),
        sa.Column("parser", sa.String(64), nullable=False),
        sa.Column("text_represents", sa.String(16), nullable=False),
        # [{"number", "depends_on", "structure_source", "warnings"}], plus set-level warnings.
        sa.Column("claims_snapshot", JSONB(), nullable=False),
        sa.Column("product_feature_set_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_document_id"], ["patent_claim_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_feature_set_id"], ["product_feature_sets.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("claims_text_sha256 ~ '^[0-9a-f]{64}$'", name="ck_fto_charts_sha256"),
    )
    op.create_index("ix_fto_charts_case", "fto_charts", ["case_id", "created_at"])

    op.create_table(
        "fto_chart_claim_features",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("chart_id", sa.Uuid(), nullable=False),
        sa.Column("feature_id", sa.String(16), nullable=False),
        sa.Column("claim_number", sa.Integer(), nullable=False),
        sa.Column("feature_text", sa.Text(), nullable=False),
        sa.Column("spans", JSONB(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("confirmed_by_identity_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("chart_id", "feature_id"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["chart_id"], ["fto_charts.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(confirmed_by_identity_id IS NULL) = (confirmed_at IS NULL)", name="ck_fto_claim_features_confirmation"
        ),
    )

    op.create_table(
        "fto_feature_findings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("chart_id", sa.Uuid(), nullable=False),
        sa.Column("feature_id", sa.String(16), nullable=False),
        sa.Column("finding", sa.String(24), nullable=False),
        sa.Column("product_feature_codes", ARRAY(sa.Text()), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("assessed_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["chart_id", "feature_id"],
            ["fto_chart_claim_features.chart_id", "fto_chart_claim_features.feature_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "finding IN (" + ", ".join(f"'{f}'" for f in FINDINGS) + ")", name="ck_fto_findings_value"
        ),
        sa.CheckConstraint(
            "finding NOT IN ('literally_present', 'present_by_equivalent') OR cardinality(product_feature_codes) > 0",
            name="ck_fto_findings_present_needs_product_feature",
        ),
        sa.CheckConstraint(
            "finding NOT IN ('present_by_equivalent', 'absent') OR length(btrim(rationale)) > 0",
            name="ck_fto_findings_rationale",
        ),
    )
    op.create_index(
        "ix_fto_findings_latest", "fto_feature_findings", ["chart_id", "feature_id", sa.text("assessed_at DESC")]
    )

    op.execute(
        """CREATE FUNCTION fto_claim_feature_confirm_only() RETURNS trigger AS $$
        BEGIN
          IF NEW.chart_id IS DISTINCT FROM OLD.chart_id
             OR NEW.feature_id IS DISTINCT FROM OLD.feature_id
             OR NEW.claim_number IS DISTINCT FROM OLD.claim_number
             OR NEW.feature_text IS DISTINCT FROM OLD.feature_text
             OR NEW.spans IS DISTINCT FROM OLD.spans
             OR NEW.sort_order IS DISTINCT FROM OLD.sort_order THEN
            RAISE EXCEPTION 'claim feature snapshot is immutable';
          END IF;
          IF OLD.confirmed_at IS NOT NULL THEN
            RAISE EXCEPTION 'claim feature confirmation cannot be changed or revoked';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """CREATE TRIGGER fto_chart_claim_features_confirm_only
        BEFORE UPDATE ON fto_chart_claim_features
        FOR EACH ROW EXECUTE FUNCTION fto_claim_feature_confirm_only()"""
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_organization_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION deny_organization_id_change()"
        )

    for role in RUNTIME_ROLES:
        op.execute(f'GRANT SELECT, INSERT ON "fto_charts" TO {role}')
        op.execute(f'GRANT SELECT, INSERT ON "fto_feature_findings" TO {role}')
        op.execute(f'GRANT SELECT, INSERT ON "fto_chart_claim_features" TO {role}')
        # Only the confirmation columns may be updated (the trigger also forbids revoking).
        op.execute(
            f'GRANT UPDATE (confirmed_by_identity_id, confirmed_at) ON "fto_chart_claim_features" TO {role}'
        )
    for table in TABLES:
        enable_force_rls(table)


def downgrade() -> None:
    op.drop_table("fto_feature_findings")
    op.drop_table("fto_chart_claim_features")
    op.drop_table("fto_charts")
    op.execute("DROP FUNCTION fto_claim_feature_confirm_only()")
