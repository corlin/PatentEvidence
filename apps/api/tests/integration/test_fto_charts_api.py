"""FTO claim charts with manual findings (ADR 0011), through the real app."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from test_support import api_settings, login_with_totp, postgres_url, reset_database, seed_admin_tenants

from patent_evidence_api.main import create_app

FTO = Path(__file__).resolve().parents[4] / "fixtures" / "fto"
ORG_A = UUID("b1000000-0000-4000-8000-000000000001")
ORG_B = UUID("b1000000-0000-4000-8000-000000000002")
ADMIN_A = UUID("b2000000-0000-4000-8000-000000000001")
CASE_A = UUID("b3000000-0000-4000-8000-000000000001")
CASE_A2 = UUID("b3000000-0000-4000-8000-000000000002")
PASSWORD = "Correct horse battery staple 42"
MFA_KEY = Fernet.generate_key().decode()
SECRET = "保密理由MARKER"  # must never reach the audit log


class Clock:
    def __init__(self) -> None:
        self.value = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def seeded() -> None:
    with psycopg.connect(postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration"), autocommit=True) as conn:
        reset_database(conn)
        seed_admin_tenants(
            conn,
            password_hash=PasswordHasher().hash(PASSWORD),
            tenants=[
                {"org_id": ORG_A, "slug": "fto-a", "display_name": "A", "admin_id": ADMIN_A, "admin_email": "admin_a_fto@tenant.com",
                 "membership_id": UUID("b4000000-0000-4000-8000-000000000001"), "monthly_case_allowance": 50},
                {"org_id": ORG_B, "slug": "fto-b", "display_name": "B", "admin_id": UUID("b2000000-0000-4000-8000-000000000002"),
                 "admin_email": "admin_b_fto@tenant.com", "membership_id": UUID("b4000000-0000-4000-8000-000000000002"),
                 "monthly_case_allowance": 50},
            ],
        )
        for case_id, number in ((CASE_A, "FTO-1"), (CASE_A2, "FTO-2")):
            conn.execute(
                "INSERT INTO cases (id, organization_id, case_number, title, technical_field, created_by_identity_id) "
                "VALUES (%s, %s, %s, '合成案件', '电池', %s)",
                (case_id, ORG_A, number, ADMIN_A),
            )
        # Fetched claim documents (public data), as the ADR 0009 fetcher would store them.
        for pub, source, text_, represents in (
            ("US-12451529-B2", "uspto_grant_xml", (FTO / "us" / "US-12451529-claims.xml").read_text(), "as_granted"),
            ("EP-3467934-B1", "epo_ops_claims", (FTO / "ep" / "EP-3467934-B1-claims.json").read_text(), "as_published"),
        ):
            conn.execute(
                """INSERT INTO patent_claim_documents (id, publication_number, source, request_ref, retrieved_at, outcome,
                   claims_text, text_represents, raw_sha256) VALUES (%s, %s, %s, 'GET test', now(), 'found', %s, %s, %s)""",
                (uuid4(), pub, source, text_, represents, "0" * 64),
            )


def _base(case: UUID = CASE_A, org: UUID = ORG_A) -> str:
    return f"/api/v1/organizations/{org}/cases/{case}"


async def _product_set(client: AsyncClient, *, confirm: bool) -> str:
    desc = (await client.post(f"{_base()}/product/descriptions", json={"text": "1. 电池模组堆叠。\n2. 上盖设有导向结构。\n3. 设有膨胀检测元件。"})).json()
    draft = (await client.post(f"{_base()}/product/descriptions/{desc['id']}/feature-sets")).json()
    if confirm:
        assert (await client.post(f"{_base()}/product/feature-sets/{draft['id']}/confirm")).status_code == 200
    return draft["id"]


def _claim(chart: dict, number: int) -> dict:
    return next(c for c in chart["claims"] if c["number"] == number)


@pytest.mark.asyncio
async def test_chart_flow_and_conclusions(seeded: None) -> None:
    clock = Clock()
    app = create_app(settings=api_settings(mfa_encryption_key=MFA_KEY), clock=clock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await login_with_totp(client, clock=clock, email="admin_a_fto@tenant.com", password=PASSWORD)

        draft_set = await _product_set(client, confirm=False)
        unconfirmed = await client.post(f"{_base()}/fto/charts", json={"publication_number": "US-12451529-B2", "product_feature_set_id": draft_set})
        assert unconfirmed.status_code == 409 and unconfirmed.json()["detail"] == "product_feature_set_not_confirmed"

        product_set = await _product_set(client, confirm=True)
        not_fetched = await client.post(f"{_base()}/fto/charts", json={"publication_number": "US-1234567-B2", "product_feature_set_id": product_set})
        assert not_fetched.status_code == 409 and not_fetched.json()["detail"] == "claims_not_fetched"

        created = await client.post(f"{_base()}/fto/charts", json={"publication_number": "US-12451529-B2", "product_feature_set_id": product_set})
        assert created.status_code == 201
        chart = created.json()
        chart_id = chart["id"]
        assert len(chart["claims"]) == 7 and _claim(chart, 2)["depends_on"] == [1]
        assert any("as granted" in c for c in chart["caveats"]) and any("not a legal opinion" in c for c in chart["caveats"])
        assert {c["conclusion"] for c in chart["claims"]} == {"undetermined"}

        claim1 = [f["feature_id"] for f in _claim(chart, 1)["features"]]
        url = f"{_base()}/fto/charts/{chart_id}/findings"
        for fid in claim1:
            r = await client.post(url, json={"feature_id": fid, "finding": "literally_present", "product_feature_codes": ["P1"]})
            assert r.status_code == 201
        # Every feature present but not yet confirmed: never "reads".
        assert _claim(r.json(), 1)["conclusion"] == "undetermined"

        confirmed = await client.post(f"{_base()}/fto/charts/{chart_id}/claims/1/confirm-features")
        assert _claim(confirmed.json(), 1)["conclusion"] == "reads_literally"
        assert _claim(confirmed.json(), 2)["conclusion"] == "undetermined"  # claim 2's own features unassessed

        absent = await client.post(url, json={"feature_id": claim1[1], "finding": "absent", "rationale": f"产品无该结构 {SECRET}"})
        after = absent.json()
        assert _claim(after, 1)["conclusion"] == "does_not_read"
        assert _claim(after, 1)["absent_features"] == [claim1[1]]
        assert _claim(after, 2)["conclusion"] == "does_not_read"  # inherits the missing feature

        history = (await client.get(f"{_base()}/fto/charts/{chart_id}/features/{claim1[1]}/findings")).json()["items"]
        assert [h["finding"] for h in history] == ["absent", "literally_present"]  # latest first, history kept

        # Input rules
        assert (await client.post(url, json={"feature_id": claim1[0], "finding": "literally_present"})).json()["detail"] == "finding_needs_product_feature"
        assert (await client.post(url, json={"feature_id": claim1[0], "finding": "absent"})).json()["detail"] == "finding_needs_rationale"
        bad_code = await client.post(url, json={"feature_id": claim1[0], "finding": "literally_present", "product_feature_codes": ["P99"]})
        assert bad_code.status_code == 422 and "P99" in bad_code.json()["detail"]
        assert (await client.post(url, json={"feature_id": "99.9", "finding": "undetermined"})).status_code == 404

        assert (await client.get(f"{_base(CASE_A2)}/fto/charts/{chart_id}")).status_code == 404  # wrong case

        ep = await client.post(f"{_base()}/fto/charts", json={"publication_number": "EP-3467934-B1", "product_feature_set_id": product_set})
        assert ep.status_code == 201 and any("translation" in c for c in ep.json()["caveats"])

    with psycopg.connect(postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")) as conn:
        summaries = [r[0] for r in conn.execute(
            "SELECT safe_summary FROM audit_events WHERE organization_id = %s AND action LIKE 'case.fto.%%'", (ORG_A,)
        ).fetchall()]
    assert summaries and all(SECRET not in s and "产品无该结构" not in s for s in summaries)


@pytest.mark.asyncio
async def test_other_tenant_and_database_immutability(seeded: None) -> None:
    clock = Clock()
    app = create_app(settings=api_settings(mfa_encryption_key=MFA_KEY), clock=clock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await login_with_totp(client, clock=clock, email="admin_a_fto@tenant.com", password=PASSWORD)
        product_set = await _product_set(client, confirm=True)
        chart = (await client.post(f"{_base()}/fto/charts", json={"publication_number": "US-12451529-B2", "product_feature_set_id": product_set})).json()
        await client.post(f"{_base()}/fto/charts/{chart['id']}/claims/1/confirm-features")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client_b:
        await login_with_totp(client_b, clock=clock, email="admin_b_fto@tenant.com", password=PASSWORD)
        assert (await client_b.get(f"{_base()}/fto/charts/{chart['id']}")).status_code == 404
        assert (await client_b.get(f"{_base(org=ORG_B)}/fto/charts/{chart['id']}")).status_code == 404

    with psycopg.connect(postgres_url("PE_TEST_APPLICATION_DATABASE_URL", "patent_evidence_app"), autocommit=True) as app_db:
        app_db.execute("SELECT set_config('app.current_organization_id', %s, false)", (str(ORG_A),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # snapshot text is not updatable at all
            app_db.execute("UPDATE fto_chart_claim_features SET feature_text = 'x' WHERE chart_id = %s", (chart["id"],))
        with pytest.raises(psycopg.errors.RaiseException):  # confirmation cannot be revoked
            app_db.execute(
                "UPDATE fto_chart_claim_features SET confirmed_at = NULL, confirmed_by_identity_id = NULL "
                "WHERE chart_id = %s AND claim_number = 1", (chart["id"],)
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):  # findings are append-only
            app_db.execute("UPDATE fto_feature_findings SET finding = 'absent'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            app_db.execute("DELETE FROM fto_charts")
