#!/usr/bin/env python3
"""Seed demo data for PatentEvidence manual testing."""

import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from argon2 import PasswordHasher

PASSWORD = "Password123!"
SUPERADMIN_ID = UUID("80000000-0000-4000-8000-000000000001")
ORG_ID = UUID("90000000-0000-4000-8000-000000000001")
ADMIN_ID = UUID("91000000-0000-4000-8000-000000000001")
MEMBER_ID = UUID("92000000-0000-4000-8000-000000000001")


def main() -> None:
    db_url = os.environ.get("PATENT_EVIDENCE_MIGRATION_DATABASE_URL")
    if not db_url:
        print("Missing PATENT_EVIDENCE_MIGRATION_DATABASE_URL", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(UTC).replace(microsecond=0)
    hasher = PasswordHasher()
    pwd_hash = hasher.hash(PASSWORD)

    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # 1. Superadmin
            cur.execute(
                """INSERT INTO global_identities
                (id, email_normalized, display_name, status, password_hash, security_version, created_at, updated_at)
                VALUES
                (%s, 'superadmin@patent.com', '平台超级管理员', 'active', %s, 1, %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (SUPERADMIN_ID, pwd_hash, now, now),
            )
            cur.execute(
                """INSERT INTO platform_operator_grants
                (id, global_identity_id, role, status, granted_by, granted_at, bootstrap_mfa_enrollment_expires_at)
                VALUES
                (%s, %s, 'platform_admin', 'active', NULL, %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (UUID("81000000-0000-4000-8000-000000000001"), SUPERADMIN_ID, now, now + timedelta(days=365)),
            )

            # 2. Organization
            cur.execute(
                """INSERT INTO organizations
                (id, slug, display_name, status, created_by, created_at, updated_at)
                VALUES
                (%s, 'qianyan-ip', '北京前沿知识产权代理事务所', 'active', %s, %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (ORG_ID, SUPERADMIN_ID, now, now),
            )
            cur.execute(
                """INSERT INTO organization_plan_quotas
                (organization_id, plan_key, monthly_case_allowance, current_period_start, current_period_end, status, created_at, updated_at)
                VALUES
                (%s, 'standard', 100, %s, %s, 'active', %s, %s)
                ON CONFLICT (organization_id) DO NOTHING""",
                (ORG_ID, now - timedelta(days=1), now + timedelta(days=29), now, now),
            )

            # 3. Tenant Admin
            cur.execute(
                """INSERT INTO global_identities
                (id, email_normalized, display_name, status, password_hash, security_version, created_at, updated_at)
                VALUES
                (%s, 'partner@patent.com', '张资深合伙人', 'active', %s, 1, %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (ADMIN_ID, pwd_hash, now, now),
            )
            cur.execute(
                """INSERT INTO organization_memberships
                (id, organization_id, global_identity_id, role, status, created_at, updated_at)
                VALUES
                (%s, %s, %s, 'organization_admin', 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (MEMBER_ID, ORG_ID, ADMIN_ID, now, now),
            )
            cur.execute(
                """INSERT INTO organization_memberships
                (id, organization_id, global_identity_id, role, status, created_at, updated_at)
                VALUES
                (%s, %s, %s, 'organization_admin', 'active', %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (UUID("82000000-0000-4000-8000-000000000001"), ORG_ID, SUPERADMIN_ID, now, now),
            )

            # 4. Demo Case
            case_id = UUID("93000000-0000-4000-8000-000000000001")
            cur.execute(
                """INSERT INTO cases
                (id, organization_id, case_number, title, technical_field, target_jurisdiction, status, created_by_identity_id, created_at, updated_at)
                VALUES
                (%s, %s, '2026-PAT-DEMO-001', '一种面向大语言模型的稀疏矩阵量化加速系统', '人工智能与大模型计算', 'CN', 'draft', %s, %s, %s)
                ON CONFLICT (id) DO NOTHING""",
                (case_id, ORG_ID, ADMIN_ID, now, now),
            )

    print("Demo data seeded successfully!")
    print(f"Superadmin: superadmin@patent.com / {PASSWORD}")
    print(f"Tenant Admin: partner@patent.com / {PASSWORD}")
    print(f"Organization: 北京前沿知识产权代理事务所 (ID: {ORG_ID})")
    print(f"Demo Case: 2026-PAT-DEMO-001 (ID: {case_id})")


if __name__ == "__main__":
    main()
