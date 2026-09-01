#!/usr/bin/env python3
"""Create the first platform administrator without exposing password arguments."""

import argparse
import asyncio
import getpass
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api" / "src"))

from patent_evidence_api.auth.security import PasswordSecurity
from patent_evidence_api.core.settings import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

PASSWORD_ENVIRONMENT_VARIABLE = "PATENT_EVIDENCE_BOOTSTRAP_PASSWORD"
MFA_HANDOFF_LIFETIME = timedelta(minutes=30)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        self.print_usage(sys.stderr)
        self.exit(2, "bootstrap-platform-admin.py: invalid command arguments\n")


async def append_bootstrap_audit(
    connection: AsyncConnection,
    *,
    actor: UUID | None,
    target: UUID | None,
    result: str,
    correlation: str,
    summary: str,
    now: datetime,
) -> None:
    await connection.execute(
        text(
            """INSERT INTO platform_audit_events
            (id,actor_identity_id,action,target_type,target_id,result,
             request_correlation_id,safe_summary,created_at)
            VALUES (:id,:actor,'platform.admin.bootstrap','global_identity',:target,
                    :result,:correlation,:summary,:now)"""
        ),
        {
            "id": uuid4(),
            "actor": actor,
            "target": target,
            "result": result,
            "correlation": correlation,
            "summary": summary,
            "now": now,
        },
    )


def parser() -> argparse.ArgumentParser:
    command = SafeArgumentParser(
        description="Create the first platform administrator. Password is read from a secure prompt or environment."
    )
    command.add_argument("email")
    command.add_argument("display_name")
    return command


async def bootstrap(email: str, display_name: str, password: str) -> datetime:
    settings = Settings()
    if not settings.migration_database_url:
        raise RuntimeError("PATENT_EVIDENCE_MIGRATION_DATABASE_URL is required")
    database_url = settings.migration_database_url.replace(
        "postgresql+psycopg://", "postgresql+asyncpg://", 1
    ).replace("postgresql://", "postgresql+asyncpg://", 1)
    password_hash = PasswordSecurity().hash(password)
    identity_id = uuid4()
    now = datetime.now(UTC)
    deadline = now + MFA_HANDOFF_LIFETIME
    failure: str | None = None
    correlation = f"bootstrap-cli:{uuid4()}"
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("LOCK TABLE platform_operator_grants IN EXCLUSIVE MODE")
            )
            existing = await connection.scalar(
                text("SELECT EXISTS(SELECT 1 FROM platform_operator_grants)")
            )
            if existing:
                failure = "a platform administrator grant already exists"
            normalized_email = email.strip().lower()
            normalized_display_name = display_name.strip()
            if failure is None and "@" not in normalized_email:
                failure = "a valid administrator email is required"
            if failure is None and not normalized_display_name:
                failure = "an administrator display name is required"
            if failure is None:
                email_exists = await connection.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM global_identities WHERE email_normalized=:email)"
                    ),
                    {"email": normalized_email},
                )
                if email_exists:
                    failure = "the administrator email is already registered"
            if failure is None:
                await connection.execute(
                    text(
                        """INSERT INTO global_identities
                        (id,email_normalized,display_name,status,password_hash,security_version,
                         created_at,updated_at)
                        VALUES (:id,:email,:name,'active',:password_hash,1,:now,:now)"""
                    ),
                    {
                        "id": identity_id,
                        "email": normalized_email,
                        "name": normalized_display_name,
                        "password_hash": password_hash,
                        "now": now,
                    },
                )
                await connection.execute(
                    text(
                        """INSERT INTO platform_operator_grants
                        (id,global_identity_id,role,status,granted_by,granted_at,
                         bootstrap_mfa_enrollment_expires_at)
                        VALUES (:id,:identity,'platform_admin','active',NULL,:now,:deadline)"""
                    ),
                    {
                        "id": uuid4(),
                        "identity": identity_id,
                        "now": now,
                        "deadline": deadline,
                    },
                )
            await append_bootstrap_audit(
                connection,
                actor=identity_id if failure is None else None,
                target=identity_id if failure is None else None,
                result="allowed" if failure is None else "denied",
                correlation=correlation,
                summary="first platform administrator created"
                if failure is None
                else "platform administrator bootstrap rejected",
                now=now,
            )
    except Exception as exc:
        try:
            async with engine.begin() as audit_connection:
                await append_bootstrap_audit(
                    audit_connection,
                    actor=None,
                    target=None,
                    result="failed",
                    correlation=correlation,
                    summary="platform administrator bootstrap failed",
                    now=datetime.now(UTC),
                )
        except Exception:
            pass
        raise RuntimeError("platform administrator bootstrap failed") from exc
    finally:
        await engine.dispose()
    if failure is not None:
        raise RuntimeError(failure)
    return deadline


def main() -> int:
    arguments = parser().parse_args()
    password = os.environ.get(PASSWORD_ENVIRONMENT_VARIABLE)
    if password is None:
        password = getpass.getpass("Initial password: ")
    try:
        PasswordSecurity().validate(password)
        deadline = asyncio.run(
            bootstrap(arguments.email, arguments.display_name, password)
        )
    except (ValueError, RuntimeError) as error:
        print(f"bootstrap failed: {error}", file=sys.stderr)
        return 1
    finally:
        password = ""
    print("Platform administrator created. No credential material was printed.")
    print(
        "Log in, enroll and confirm TOTP, then complete the first privileged action "
        f"before the operator handoff deadline {deadline.isoformat()}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
