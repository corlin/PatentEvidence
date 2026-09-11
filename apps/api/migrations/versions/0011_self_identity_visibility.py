"""Add self-identity visibility policies for /me and organization pickers.

Revision ID: 0011_self_identity_visibility
Revises: 0010_review_and_delivery
"""

from alembic import op

revision = "0011_self_identity_visibility"
down_revision = "0010_review_and_delivery"


def upgrade() -> None:
    # A user can always see their own memberships (across organizations),
    # which is what GET /api/v1/auth/me and the organization picker need.
    op.execute(
        """CREATE POLICY organization_memberships_self_visibility
        ON organization_memberships
        TO patent_evidence_app
        USING (
          global_identity_id = nullif(
            current_setting('app.current_actor_identity_id', true), ''
          )::uuid
        )
        WITH CHECK (false)"""
    )
    # The user can also see the display name of organizations they belong to,
    # without seeing unrelated tenants.
    op.execute(
        """CREATE POLICY organizations_self_tenant_visibility
        ON organizations
        TO patent_evidence_app
        USING (
          id IN (
            SELECT organization_id FROM organization_memberships
            WHERE global_identity_id = nullif(
              current_setting('app.current_actor_identity_id', true), ''
            )::uuid
          )
        )"""
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS organizations_self_tenant_visibility ON organizations"
    )
    op.execute(
        "DROP POLICY IF EXISTS organization_memberships_self_visibility ON organization_memberships"
    )
