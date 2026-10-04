"""Product description and feature API (ADR 0010) through the real app: auth, audit, tenancy."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from test_support import api_settings, login_with_totp, postgres_url, reset_database, seed_admin_tenants

from patent_evidence_api.main import create_app

ORG_A = UUID("a1000000-0000-4000-8000-000000000001")
ORG_B = UUID("a1000000-0000-4000-8000-000000000002")
ADMIN_A = UUID("a2000000-0000-4000-8000-000000000001")
ADMIN_B = UUID("a2000000-0000-4000-8000-000000000002")
CASE_A = UUID("a3000000-0000-4000-8000-000000000001")
CASE_A2 = UUID("a3000000-0000-4000-8000-000000000002")
PASSWORD = "Correct horse battery staple 42"
MFA_KEY = Fernet.generate_key().decode()
# SYNTHETIC test text; the marker string lets us prove it never reaches the audit log.
SECRET_MARKER = "保密冷却结构XYZ"
DESCRIPTION = f"1. 液冷板由铝合金挤压成型，厚度为2.5 mm。\n2. {SECRET_MARKER}流道呈蛇形布置；入口与出口位于同一侧。"


class Clock:
    def __init__(self) -> None:
        self.value = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def seeded() -> None:
    with psycopg.connect(
        postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"), autocommit=True
    ) as conn:
        reset_database(conn)
        seed_admin_tenants(
            conn,
            password_hash=PasswordHasher().hash(PASSWORD),
            tenants=[
                {"org_id": ORG_A, "slug": "prod-org-a", "display_name": "A", "admin_id": ADMIN_A,
                 "admin_email": "admin_a_prod@tenant.com", "membership_id": UUID("a4000000-0000-4000-8000-000000000001"),
                 "monthly_case_allowance": 50},
                {"org_id": ORG_B, "slug": "prod-org-b", "display_name": "B", "admin_id": ADMIN_B,
                 "admin_email": "admin_b_prod@tenant.com", "membership_id": UUID("a4000000-0000-4000-8000-000000000002"),
                 "monthly_case_allowance": 50},
            ],
        )
        for case_id, number in ((CASE_A, "FTO-1"), (CASE_A2, "FTO-2")):
            conn.execute(
                """INSERT INTO cases (id, organization_id, case_number, title, technical_field, created_by_identity_id)
                VALUES (%s, %s, %s, '合成案件', '电池热管理', %s)""",
                (case_id, ORG_A, number, ADMIN_A),
            )


def _base(case: UUID = CASE_A, org: UUID = ORG_A) -> str:
    return f"/api/v1/organizations/{org}/cases/{case}/product"


@pytest.mark.asyncio
async def test_description_to_confirmed_features_flow(seeded: None) -> None:
    clock = Clock()
    app = create_app(settings=api_settings(mfa_encryption_key=MFA_KEY), clock=clock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await login_with_totp(client, clock=clock, email="admin_a_prod@tenant.com", password=PASSWORD)

        created = await client.post(f"{_base()}/descriptions", json={"text": DESCRIPTION})
        assert created.status_code == 201 and created.json()["version_number"] == 1
        listed = (await client.get(f"{_base()}/descriptions")).json()["items"]
        assert listed[0]["text"] == DESCRIPTION

        draft = await client.post(f"{_base()}/descriptions/{created.json()['id']}/feature-sets")
        assert draft.status_code == 201
        set_id = draft.json()["id"]
        assert [f["code"] for f in draft.json()["features"]] == ["P1", "P2", "P3"]

        merged = await client.post(f"{_base()}/feature-sets/{set_id}/merge", json={"codes": ["P2", "P3"]})
        assert merged.status_code == 200 and len(merged.json()["features"]) == 2
        edited = await client.patch(f"{_base()}/feature-sets/{set_id}/features/P1", json={"text": "液冷板为铝合金挤压件，厚度2.5 mm。"})
        assert next(f for f in edited.json()["features"] if f["code"] == "P1")["origin"] == "edited"
        added = await client.post(f"{_base()}/feature-sets/{set_id}/features", json={"text": "箱体为钢制。"})
        assert added.status_code == 201
        split = await client.post(f"{_base()}/feature-sets/{set_id}/features/P2/split", json={"at": 2})
        assert split.status_code == 200

        # A set must be addressed through its own case.
        wrong_case = await client.get(f"{_base(CASE_A2)}/feature-sets/{set_id}")
        assert wrong_case.status_code == 404

        confirmed = await client.post(f"{_base()}/feature-sets/{set_id}/confirm")
        assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
        late = await client.post(f"{_base()}/feature-sets/{set_id}/features", json={"text": "不应成功"})
        assert late.status_code == 409

        revision = await client.post(f"{_base()}/feature-sets/{set_id}/revisions")
        assert revision.status_code == 201 and revision.json()["parent_set_id"] == set_id
        sets = (await client.get(f"{_base()}/feature-sets")).json()["items"]
        assert [s["status"] for s in sets] == ["draft", "confirmed"]

    with psycopg.connect(postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")) as conn:
        audit = conn.execute(
            "SELECT action, safe_summary FROM audit_events WHERE organization_id = %s AND action LIKE 'case.product.%%'",
            (ORG_A,),
        ).fetchall()
    actions = {a for a, _ in audit}
    assert {"case.product.description.add", "case.product.features.draft", "case.product.features.confirm"} <= actions
    assert all(SECRET_MARKER not in summary and "液冷板" not in summary for _, summary in audit)


@pytest.mark.asyncio
async def test_other_tenant_cannot_read_or_write(seeded: None) -> None:
    clock = Clock()
    app = create_app(settings=api_settings(mfa_encryption_key=MFA_KEY), clock=clock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await login_with_totp(client, clock=clock, email="admin_a_prod@tenant.com", password=PASSWORD)
        created = (await client.post(f"{_base()}/descriptions", json={"text": DESCRIPTION})).json()
        set_id = (await client.post(f"{_base()}/descriptions/{created['id']}/feature-sets")).json()["id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client_b:
        await login_with_totp(client_b, clock=clock, email="admin_b_prod@tenant.com", password=PASSWORD)
        # Organization B addressing organization A's resources is not a member: 404, nothing revealed.
        assert (await client_b.get(f"{_base()}/descriptions")).status_code == 404
        assert (await client_b.get(f"{_base()}/feature-sets/{set_id}")).status_code == 404
        # Through its own organization, A's set id does not exist.
        own = await client_b.get(f"{_base(org=ORG_B)}/feature-sets/{set_id}")
        assert own.status_code == 404


@pytest.mark.asyncio
async def test_invalid_bodies_are_rejected(seeded: None) -> None:
    clock = Clock()
    app = create_app(settings=api_settings(mfa_encryption_key=MFA_KEY), clock=clock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await login_with_totp(client, clock=clock, email="admin_a_prod@tenant.com", password=PASSWORD)
        assert (await client.post(f"{_base()}/descriptions", json={"text": ""})).status_code == 422
        assert (await client.post(f"{_base()}/descriptions", json={"text": "   "})).status_code == 422
