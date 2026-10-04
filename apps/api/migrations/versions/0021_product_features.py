"""Product descriptions and their confirmed technical features (ADR 0010).

Revision ID: 0021_product_features
Revises: 0020_claim_documents

Customer-confidential data: tenant tables with FORCE RLS. Descriptions are
append-only. A feature set is editable while "draft"; once "confirmed" the
set and its features cannot be changed or deleted, enforced by triggers (the
immutable approval boundary), not only by application code.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from helpers.tenancy import enable_force_rls

revision = "0021_product_features"
down_revision = "0020_claim_documents"
branch_labels = None
depends_on = None

RUNTIME_ROLES = ("patent_evidence_app", "patent_evidence_worker")
TABLES = ("product_descriptions", "product_feature_sets", "product_features")


def upgrade() -> None:
    op.create_table(
        "product_descriptions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("description_text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("created_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("case_id", "version_number", name="uq_product_descriptions_case_version"),
        sa.CheckConstraint("text_sha256 ~ '^[0-9a-f]{64}$'", name="ck_product_descriptions_sha256"),
        sa.CheckConstraint("length(description_text) > 0", name="ck_product_descriptions_not_empty"),
    )

    op.create_table(
        "product_feature_sets",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("description_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_set_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("splitter_version", sa.String(64), nullable=False),
        sa.Column("created_by_identity_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("confirmed_by_identity_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["description_id"], ["product_descriptions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_set_id"], ["product_feature_sets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("case_id", "version_number", name="uq_product_feature_sets_case_version"),
        sa.CheckConstraint("status IN ('draft', 'confirmed')", name="ck_product_feature_sets_status"),
        sa.CheckConstraint(
            "(status = 'confirmed') = (confirmed_by_identity_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_product_feature_sets_confirmation",
        ),
    )

    op.create_table(
        "product_features",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("feature_set_id", sa.Uuid(), nullable=False),
        sa.Column("feature_code", sa.String(16), nullable=False),
        sa.Column("feature_text", sa.Text(), nullable=False),
        # [[start, end], ...] offsets into the description text; [] for manual features.
        sa.Column("spans", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("origin", sa.String(8), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["feature_set_id"], ["product_feature_sets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("feature_set_id", "feature_code", name="uq_product_features_set_code"),
        sa.CheckConstraint("origin IN ('split', 'manual', 'edited')", name="ck_product_features_origin"),
        sa.CheckConstraint("length(feature_text) > 0", name="ck_product_features_not_empty"),
    )
    op.create_index("ix_product_features_set", "product_features", ["feature_set_id", "sort_order"])

    op.execute(
        """CREATE FUNCTION deny_confirmed_product_feature_set_change() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'confirmed' THEN
            RAISE EXCEPTION 'confirmed product feature set % is immutable', OLD.id;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """CREATE TRIGGER product_feature_sets_confirmed_immutable
        BEFORE UPDATE OR DELETE ON product_feature_sets
        FOR EACH ROW EXECUTE FUNCTION deny_confirmed_product_feature_set_change()"""
    )
    op.execute(
        """CREATE FUNCTION deny_features_of_confirmed_set() RETURNS trigger AS $$
        DECLARE
          target uuid;
        BEGIN
          FOR target IN
            SELECT unnest(ARRAY[
              CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN OLD.feature_set_id END,
              CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN NEW.feature_set_id END])
          LOOP
            IF target IS NOT NULL AND EXISTS (
              SELECT 1 FROM product_feature_sets WHERE id = target AND status = 'confirmed'
            ) THEN
              RAISE EXCEPTION 'features of confirmed product feature set % are immutable', target;
            END IF;
          END LOOP;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """CREATE TRIGGER product_features_confirmed_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON product_features
        FOR EACH ROW EXECUTE FUNCTION deny_features_of_confirmed_set()"""
    )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_organization_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION deny_organization_id_change()"
        )

    for role in RUNTIME_ROLES:
        op.execute(f'GRANT SELECT, INSERT ON "product_descriptions" TO {role}')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "product_feature_sets" TO {role}')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "product_features" TO {role}')
    for table in TABLES:
        enable_force_rls(table)


def downgrade() -> None:
    op.drop_table("product_features")
    op.drop_table("product_feature_sets")
    op.drop_table("product_descriptions")
    op.execute("DROP FUNCTION deny_features_of_confirmed_set()")
    op.execute("DROP FUNCTION deny_confirmed_product_feature_set_change()")
