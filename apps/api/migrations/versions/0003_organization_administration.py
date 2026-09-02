"""Add invitation-token access and pending invitation uniqueness.

Revision ID: 0003_organization_administration
Revises: 0002_platform_provisioning
"""

from alembic import op

revision = "0003_organization_administration"
down_revision = "0002_platform_provisioning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """CREATE UNIQUE INDEX uq_organization_invitations_pending_email
        ON organization_invitations (organization_id,email_normalized)
        WHERE status='pending'"""
    )
    op.execute(
        """CREATE POLICY organization_invitations_token_inspection
        ON organization_invitations FOR SELECT TO patent_evidence_app
        USING (token_hash = nullif(
          current_setting('app.current_invitation_token_hash', true), ''
        ))"""
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS organization_invitations_token_inspection "
        "ON organization_invitations"
    )
    op.execute("DROP INDEX IF EXISTS uq_organization_invitations_pending_email")
