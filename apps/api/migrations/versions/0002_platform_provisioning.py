"""Add platform organization provisioning and idempotency records.

Revision ID: 0002_platform_provisioning
Revises: 0001_identity_tenancy
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_platform_provisioning"
down_revision = "0001_identity_tenancy"
branch_labels = None
depends_on = None


def _uuid(name: str, *, primary_key: bool = False) -> sa.Column:
    return sa.Column(name, sa.Uuid(), primary_key=primary_key, nullable=False)


def upgrade() -> None:
    op.add_column(
        "platform_operator_grants",
        sa.Column(
            "bootstrap_mfa_enrollment_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        """UPDATE organizations
        SET expires_at=coalesce(expires_at,now()),status='active',updated_at=now()
        WHERE status='expired'"""
    )
    op.execute(
        """UPDATE organization_plan_quotas
        SET status='active',updated_at=now() WHERE status='expired'"""
    )
    op.drop_constraint("organizations_status_check", "organizations", type_="check")
    op.create_check_constraint(
        "organizations_status_check",
        "organizations",
        "status IN ('active','suspended')",
    )
    op.drop_constraint(
        "organization_plan_quotas_status_check",
        "organization_plan_quotas",
        type_="check",
    )
    op.create_check_constraint(
        "organization_plan_quotas_status_check",
        "organization_plan_quotas",
        "status IN ('active','suspended')",
    )
    op.create_table(
        "organization_provisioning_records",
        _uuid("id", primary_key=True),
        _uuid("organization_id"),
        _uuid("initial_invitation_id"),
        _uuid("created_by"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "initial_invitation_id"],
            ["organization_invitations.organization_id", "organization_invitations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["global_identities.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("organization_id"),
        sa.CheckConstraint("status IN ('ready','failed')"),
    )
    op.create_table(
        "organization_provisioning_requests",
        _uuid("id", primary_key=True),
        _uuid("actor_identity_id"),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        _uuid("organization_id"),
        sa.Column("response_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("actor_identity_id", "idempotency_key"),
        sa.CheckConstraint("char_length(idempotency_key) BETWEEN 8 AND 128"),
        sa.CheckConstraint("char_length(request_fingerprint) = 64"),
    )
    op.execute(
        "GRANT SELECT, INSERT ON organization_provisioning_records "
        "TO patent_evidence_platform"
    )
    op.execute(
        "GRANT SELECT, INSERT ON organization_provisioning_requests "
        "TO patent_evidence_platform"
    )


def downgrade() -> None:
    op.drop_table("organization_provisioning_requests")
    op.drop_table("organization_provisioning_records")
    op.drop_constraint(
        "organization_plan_quotas_status_check",
        "organization_plan_quotas",
        type_="check",
    )
    op.create_check_constraint(
        "organization_plan_quotas_status_check",
        "organization_plan_quotas",
        "status IN ('active','suspended','expired')",
    )
    op.drop_constraint("organizations_status_check", "organizations", type_="check")
    op.create_check_constraint(
        "organizations_status_check",
        "organizations",
        "status IN ('active','suspended','expired')",
    )
    op.drop_column("platform_operator_grants", "bootstrap_mfa_enrollment_expires_at")
