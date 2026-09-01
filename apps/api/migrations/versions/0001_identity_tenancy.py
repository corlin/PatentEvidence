"""Create identity, tenancy, credential, session, and audit foundations.

Revision ID: 0001_identity_tenancy
Revises:
"""

import sqlalchemy as sa
from alembic import op
from helpers.tenancy import (
    add_platform_policy,
    enable_force_rls,
    enable_force_session_token_rls,
)


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
        op.execute(
            f"GRANT CONNECT ON DATABASE {op.get_bind().dialect.identifier_preparer.quote(op.get_bind().engine.url.database)} TO {role}"
        )
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
        sa.ForeignKeyConstraint(
            ["created_by"], ["global_identities.id"], ondelete="RESTRICT"
        ),
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
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
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
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("monthly_case_allowance >= 0"),
        sa.CheckConstraint("current_period_end > current_period_start"),
        sa.CheckConstraint("status IN ('active','suspended','expired')"),
    )
    op.create_table(
        "user_sessions",
        _uuid("id", primary_key=True),
        _uuid("global_identity_id"),
        sa.Column("security_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
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
        sa.ForeignKeyConstraint(
            ["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["global_identities.id"], ondelete="RESTRICT"
        ),
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
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["global_identities.id"], ondelete="RESTRICT"
        ),
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
        sa.ForeignKeyConstraint(
            ["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
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
        sa.ForeignKeyConstraint(
            ["global_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("global_identity_id", "id"),
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
        sa.ForeignKeyConstraint(
            ["global_identity_id", "mfa_credential_id"],
            ["mfa_credentials.global_identity_id", "mfa_credentials.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("mfa_credential_id", "code_hash"),
    )
    op.create_index(
        "uq_mfa_credentials_one_active_per_identity",
        "mfa_credentials",
        ["global_identity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_mfa_credentials_one_pending_per_identity",
        "mfa_credentials",
        ["global_identity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
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
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actor_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
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
        sa.ForeignKeyConstraint(
            ["actor_identity_id"], ["global_identities.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint("result IN ('allowed','denied','failed')"),
    )

    for table in TENANT_TABLES:
        enable_force_rls(
            table,
            organization_column="id" if table == "organizations" else "organization_id",
        )
    enable_force_session_token_rls("user_sessions")
    for table in (
        "organizations",
        "organization_plan_quotas",
        "organization_invitations",
    ):
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

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON global_identities TO patent_evidence_app"
    )
    op.execute(
        "GRANT INSERT, UPDATE (used_at) ON password_reset_tokens TO patent_evidence_app"
    )
    op.execute(
        "GRANT SELECT (global_identity_id,used_at) ON password_reset_tokens TO patent_evidence_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_credentials TO patent_evidence_app"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON mfa_recovery_codes TO patent_evidence_app"
    )
    op.execute(
        "GRANT SELECT ON organizations, organization_plan_quotas TO patent_evidence_app"
    )
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
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON organizations, organization_plan_quotas TO patent_evidence_platform"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON organization_invitations TO patent_evidence_platform"
    )
    op.execute(
        "GRANT SELECT, INSERT ON platform_audit_events TO patent_evidence_platform"
    )

    op.execute(
        """CREATE FUNCTION revoke_current_identity_sessions(requested_identity uuid)
        RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE affected integer;
        DECLARE authenticated_identity uuid;
        DECLARE correlation text;
        BEGIN
          SELECT session.global_identity_id INTO authenticated_identity
          FROM public.user_sessions session
          JOIN public.global_identities identity
            ON identity.id=session.global_identity_id
          WHERE session.token_hash = nullif(
              current_setting('app.current_session_token_hash', true), ''
            )
            AND session.revoked_at IS NULL AND session.expires_at > now()
            AND session.security_version=identity.security_version
            AND identity.status='active';
          IF authenticated_identity IS NULL OR authenticated_identity IS DISTINCT FROM requested_identity THEN
            RAISE EXCEPTION 'current session identity mismatch';
          END IF;
          UPDATE public.user_sessions SET revoked_at=now(),updated_at=now()
          WHERE global_identity_id=requested_identity AND revoked_at IS NULL;
          GET DIAGNOSTICS affected = ROW_COUNT;
          correlation := coalesce(nullif(
            current_setting('app.current_request_correlation_id', true), ''
          ), 'missing');
          INSERT INTO public.platform_audit_events
            (id,actor_identity_id,action,target_type,target_id,result,
             request_correlation_id,safe_summary,created_at)
          VALUES (gen_random_uuid(),authenticated_identity,'identity.sessions_revoke',
                  'global_identity',requested_identity,'allowed',correlation,
                  'Revoked identity sessions',now());
          RETURN affected;
        END;
        $$"""
    )
    op.execute(
        """CREATE FUNCTION complete_password_reset(requested_token_hash text, new_password_hash text)
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE reset_identity uuid;
        BEGIN
          SELECT global_identity_id INTO reset_identity
          FROM public.password_reset_tokens
          WHERE token_hash=requested_token_hash AND used_at IS NULL AND expires_at > now()
          FOR UPDATE;
          IF reset_identity IS NULL THEN
            RETURN NULL;
          END IF;
          UPDATE public.password_reset_tokens SET used_at=now()
          WHERE token_hash=requested_token_hash;
          UPDATE public.global_identities
          SET password_hash=new_password_hash,security_version=security_version+1,updated_at=now()
          WHERE id=reset_identity AND status='active';
          IF NOT FOUND THEN
            RETURN NULL;
          END IF;
          UPDATE public.user_sessions SET revoked_at=now(),updated_at=now()
          WHERE global_identity_id=reset_identity AND revoked_at IS NULL;
          INSERT INTO public.platform_audit_events
            (id,actor_identity_id,action,target_type,target_id,result,
             request_correlation_id,safe_summary,created_at)
          VALUES (gen_random_uuid(),reset_identity,'identity.password_reset',
                  'global_identity',reset_identity,'allowed','missing',
                  'Completed password reset',now());
          RETURN reset_identity;
        END;
        $$"""
    )
    op.execute(
        """CREATE FUNCTION reset_identity_mfa_as_organization_administrator(
          target_identity uuid, requested_organization uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE actor_identity uuid;
        DECLARE actor_session uuid;
        DECLARE correlation text;
        DECLARE authorized boolean := false;
        BEGIN
          SELECT session.id,session.global_identity_id INTO actor_session,actor_identity
          FROM public.user_sessions session
          JOIN public.global_identities identity
            ON identity.id=session.global_identity_id
          WHERE session.token_hash = nullif(
              current_setting('app.current_session_token_hash', true), ''
            )
            AND session.revoked_at IS NULL AND session.expires_at > now()
            AND session.mfa_verified_at >= now() - interval '10 minutes'
            AND session.security_version=identity.security_version
            AND identity.status='active';
          IF actor_identity IS NULL OR actor_identity = target_identity THEN
            RETURN false;
          END IF;
          SELECT EXISTS(
            SELECT 1 FROM public.organizations organization
            JOIN public.organization_memberships actor
              ON actor.organization_id=organization.id
            JOIN public.organization_memberships target
              ON target.organization_id=organization.id
            WHERE organization.id=requested_organization
              AND organization.status='active'
              AND actor.global_identity_id=actor_identity
              AND actor.role='organization_admin' AND actor.status='active'
              AND target.global_identity_id=target_identity
              AND target.role <> 'organization_admin' AND target.status='active'
          ) INTO authorized;
          IF NOT authorized THEN
            RETURN false;
          END IF;
          DELETE FROM public.mfa_recovery_codes WHERE global_identity_id=target_identity;
          DELETE FROM public.mfa_credentials WHERE global_identity_id=target_identity;
          UPDATE public.user_sessions SET revoked_at=now(),updated_at=now()
          WHERE global_identity_id=target_identity AND revoked_at IS NULL;
          correlation := coalesce(nullif(current_setting('app.current_request_correlation_id', true), ''), 'missing');
          INSERT INTO public.audit_events
            (id,organization_id,actor_identity_id,action,target_type,target_id,result,
             request_correlation_id,safe_summary,created_at)
          VALUES (gen_random_uuid(),requested_organization,actor_identity,'identity.mfa_reset',
                  'global_identity',target_identity,'allowed',correlation,'Reset member MFA',now());
          RETURN true;
        END;
        $$"""
    )
    op.execute(
        """CREATE FUNCTION reset_identity_mfa_as_platform_administrator(
          actor_identity uuid, actor_security_version integer, target_identity uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE authorized boolean := false;
        DECLARE correlation text;
        DECLARE context_actor uuid;
        BEGIN
          context_actor := nullif(
            current_setting('app.current_actor_identity_id', true), ''
          )::uuid;
          IF actor_identity IS NULL OR actor_identity = target_identity
             OR context_actor IS DISTINCT FROM actor_identity THEN
            RETURN false;
          END IF;
          SELECT EXISTS(
            SELECT 1 FROM public.global_identities identity
            JOIN public.platform_operator_grants grant_record
              ON grant_record.global_identity_id=identity.id
            WHERE identity.id=actor_identity AND identity.status='active'
              AND identity.security_version=actor_security_version
              AND grant_record.role='platform_admin' AND grant_record.status='active'
          ) INTO authorized;
          IF NOT authorized THEN
            RETURN false;
          END IF;
          DELETE FROM public.mfa_recovery_codes WHERE global_identity_id=target_identity;
          DELETE FROM public.mfa_credentials WHERE global_identity_id=target_identity;
          UPDATE public.user_sessions SET revoked_at=now(),updated_at=now()
          WHERE global_identity_id=target_identity AND revoked_at IS NULL;
          correlation := coalesce(nullif(
            current_setting('app.current_request_correlation_id', true), ''
          ), 'missing');
          INSERT INTO public.platform_audit_events
            (id,actor_identity_id,action,target_type,target_id,result,
             request_correlation_id,safe_summary,created_at)
          VALUES (gen_random_uuid(),actor_identity,'identity.mfa_reset','global_identity',
                  target_identity,'allowed',correlation,'Reset identity MFA',now());
          RETURN true;
        END;
        $$"""
    )
    for function in (
        "revoke_current_identity_sessions(uuid)",
        "complete_password_reset(text,text)",
        "reset_identity_mfa_as_organization_administrator(uuid,uuid)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO patent_evidence_app")
    op.execute(
        "REVOKE ALL ON FUNCTION reset_identity_mfa_as_platform_administrator(uuid,integer,uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION reset_identity_mfa_as_platform_administrator(uuid,integer,uuid) TO patent_evidence_platform"
    )

    op.execute("GRANT SELECT ON organizations TO patent_evidence_worker")
    op.execute(
        """GRANT SELECT (id,email_normalized,display_name,status,security_version,created_at,updated_at)
        ON global_identities TO patent_evidence_worker"""
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON organization_memberships, organization_plan_quotas, organization_invitations TO patent_evidence_worker"
    )
    op.execute("GRANT SELECT, INSERT ON audit_events TO patent_evidence_worker")


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS reset_identity_mfa_as_platform_administrator(uuid,integer,uuid)"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS reset_identity_mfa_as_organization_administrator(uuid,uuid)"
    )
    op.execute("DROP FUNCTION IF EXISTS complete_password_reset(text,text)")
    op.execute("DROP FUNCTION IF EXISTS revoke_current_identity_sessions(uuid)")
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
