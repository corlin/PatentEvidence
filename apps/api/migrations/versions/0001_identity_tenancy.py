"""Create identity, tenancy, credential, session, and audit foundations.

Revision ID: 0001_identity_tenancy
Revises:
"""

import sqlalchemy as sa
from alembic import op
from helpers.tenancy import add_platform_policy, enable_force_rls


revision = "0001_identity_tenancy"
down_revision = None
branch_labels = None
depends_on = None

RUNTIME_ROLES = (
    "patent_evidence_app",
    "patent_evidence_platform",
    "patent_evidence_worker",
)
TENANT_TABLES = (
    "organizations",
    "organization_memberships",
    "organization_plan_quotas",
    "user_sessions",
    "organization_invitations",
    "audit_events",
)


def _uuid(name: str, *, primary_key: bool = False, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Uuid(), primary_key=primary_key, nullable=nullable)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.execute(
        """DO $$
        DECLARE required_role text;
        BEGIN
          FOREACH required_role IN ARRAY ARRAY[
            'patent_evidence_app', 'patent_evidence_platform', 'patent_evidence_worker'
          ] LOOP
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = required_role) THEN
              RAISE EXCEPTION 'required database role % is missing', required_role;
            END IF;
          END LOOP;
        END $$"""
    )
    for role in RUNTIME_ROLES:
        op.execute(f"GRANT CONNECT ON DATABASE {op.get_bind().dialect.identifier_preparer.quote(op.get_bind().engine.url.database)} TO {role}")
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")

    op.create_table(
        "global_identities",
        _uuid("id", primary_key=True),
        sa.Column("email_normalized", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text()),
        sa.Column("security_version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.CheckConstraint("status IN ('pending','active','suspended','disabled')"),
    )
    op.create_table(
        "organizations",
        _uuid("id", primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        _uuid("created_by"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["created_by"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('active','suspended','expired')"),
    )
    op.create_table(
        "organization_memberships",
        _uuid("id", primary_key=True),
        _uuid("organization_id"),
        _uuid("global_identity_id"),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "global_identity_id"),
        sa.CheckConstraint("role IN ('organization_admin','patent_agent','reviewer')"),
        sa.CheckConstraint("status IN ('active','suspended','removed')"),
    )
    op.create_table(
        "organization_plan_quotas",
        _uuid("organization_id", primary_key=True),
        sa.Column("plan_key", sa.Text(), nullable=False),
        sa.Column("monthly_case_allowance", sa.Integer(), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("monthly_case_allowance >= 0"),
        sa.CheckConstraint("current_period_end > current_period_start"),
        sa.CheckConstraint("status IN ('active','suspended','expired')"),
    )
    op.create_table(
        "user_sessions",
        _uuid("id", primary_key=True),
        _uuid("organization_id", nullable=True),
        _uuid("global_identity_id"),
        _uuid("membership_id", nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "platform_operator_grants",
        _uuid("id", primary_key=True),
        _uuid("global_identity_id"),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _uuid("granted_by", nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("global_identity_id", "role"),
        sa.CheckConstraint("role = 'platform_admin'"),
        sa.CheckConstraint("status IN ('active','revoked')"),
    )
    op.create_table(
        "organization_invitations",
        _uuid("id", primary_key=True),
        _uuid("organization_id"),
        sa.Column("email_normalized", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False),
        _uuid("invited_by"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invited_by"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.CheckConstraint("role IN ('organization_admin','patent_agent','reviewer')"),
        sa.CheckConstraint("status IN ('pending','accepted','revoked','expired')"),
    )
    op.create_table(
        "password_reset_tokens",
        _uuid("id", primary_key=True),
        _uuid("global_identity_id"),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "mfa_credentials",
        _uuid("id", primary_key=True),
        _uuid("global_identity_id"),
        sa.Column("credential_type", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("encrypted_secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("credential_type = 'totp'"),
        sa.CheckConstraint("status IN ('pending','active','revoked')"),
    )
    op.create_table(
        "mfa_recovery_codes",
        _uuid("id", primary_key=True),
        _uuid("global_identity_id"),
        _uuid("mfa_credential_id"),
        _uuid("batch_id"),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["mfa_credential_id"], ["mfa_credentials.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("mfa_credential_id", "code_hash"),
    )
    op.create_table(
        "audit_events",
        _uuid("id", primary_key=True),
        _uuid("organization_id"),
        _uuid("actor_identity_id", nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        _uuid("target_id", nullable=True),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("request_correlation_id", sa.Text(), nullable=False),
        sa.Column("safe_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_identity_id"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.CheckConstraint("result IN ('allowed','denied','failed')"),
    )
    op.create_table(
        "platform_audit_events",
        _uuid("id", primary_key=True),
        _uuid("actor_identity_id", nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        _uuid("target_id", nullable=True),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("request_correlation_id", sa.Text(), nullable=False),
        sa.Column("safe_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_identity_id"], ["global_identities.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("result IN ('allowed','denied','failed')"),
    )

    for table in TENANT_TABLES:
        enable_force_rls(table, organization_column="id" if table == "organizations" else "organization_id")
    for table in ("organizations", "organization_plan_quotas", "organization_invitations"):
        add_platform_policy(table)

    op.execute(
        """CREATE FUNCTION deny_organization_id_change() RETURNS trigger AS $$
        BEGIN
          IF NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
            RAISE EXCEPTION 'organization_id is immutable';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql"""
    )
    for table in TENANT_TABLES[1:]:
        op.execute(
            f"CREATE TRIGGER {table}_organization_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION deny_organization_id_change()"
        )

    op.execute("GRANT SELECT, INSERT, UPDATE ON global_identities TO patent_evidence_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON password_reset_tokens TO patent_evidence_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_credentials TO patent_evidence_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_recovery_codes TO patent_evidence_app")
    op.execute("GRANT SELECT ON platform_operator_grants TO patent_evidence_app")
    op.execute("GRANT SELECT ON organizations, organization_plan_quotas TO patent_evidence_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON organization_memberships, user_sessions, organization_invitations TO patent_evidence_app"
    )
    op.execute("GRANT SELECT, INSERT ON audit_events TO patent_evidence_app")

    op.execute(
        """GRANT SELECT (id,email_normalized,display_name,status,security_version,created_at,updated_at)
        ON global_identities TO patent_evidence_platform"""
    )
    op.execute(
        """GRANT SELECT (id,global_identity_id,credential_type,label,status,confirmed_at,last_used_at,created_at)
        ON mfa_credentials TO patent_evidence_platform"""
    )
    op.execute("GRANT SELECT ON platform_operator_grants TO patent_evidence_platform")
    op.execute("GRANT SELECT, INSERT, UPDATE ON organizations, organization_plan_quotas TO patent_evidence_platform")
    op.execute("GRANT SELECT, INSERT, UPDATE ON organization_invitations TO patent_evidence_platform")
    op.execute("GRANT SELECT, INSERT ON platform_audit_events TO patent_evidence_platform")

    op.execute("GRANT SELECT ON organizations, global_identities TO patent_evidence_worker")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON organization_memberships, organization_plan_quotas, user_sessions, organization_invitations TO patent_evidence_worker"
    )
    op.execute("GRANT SELECT, INSERT ON audit_events TO patent_evidence_worker")


def downgrade() -> None:
    for table in reversed(TENANT_TABLES[1:]):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_organization_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS deny_organization_id_change")
    for table in (
        "platform_audit_events",
        "audit_events",
        "mfa_recovery_codes",
        "mfa_credentials",
        "password_reset_tokens",
        "organization_invitations",
        "platform_operator_grants",
        "user_sessions",
        "organization_plan_quotas",
        "organization_memberships",
        "organizations",
        "global_identities",
    ):
        op.drop_table(table)
