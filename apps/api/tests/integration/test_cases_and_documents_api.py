import base64
import io
import zipfile
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
import pytest
from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from docx import Document
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from adapters.object_storage.client import ObjectStorageClient
from apps.worker.src.patent_evidence_worker.parse_worker import ParseTaskWorker
from patent_evidence_api.core.database import (
    create_application_session_factory,
    create_engine,
    create_worker_session_factory,
)
from patent_evidence_api.main import create_app
from test_support import reset_database, seed_admin_tenants, api_settings, login_with_totp, login_with_existing_totp, postgres_url

ORG_A = UUID("60000000-0000-4000-8000-000000000001")
ORG_B = UUID("60000000-0000-4000-8000-000000000002")
ADMIN_A = UUID("61000000-0000-4000-8000-000000000001")
ADMIN_B = UUID("61000000-0000-4000-8000-000000000002")
MEMBER_A = UUID("62000000-0000-4000-8000-000000000001")
MEMBER_B = UUID("62000000-0000-4000-8000-000000000002")
PASSWORD = "Correct horse battery staple 42"
MFA_KEY = Fernet.generate_key().decode()


class Clock:
    def __init__(self) -> None:
        self.value = datetime.now(UTC).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.value


def _seed_org_and_identities(migration_url: str, now: datetime) -> None:
    password_hash = PasswordHasher().hash(PASSWORD)
    with psycopg.connect(migration_url, autocommit=True) as conn:
        reset_database(conn)
        seed_admin_tenants(
            conn,
            password_hash=password_hash,
            tenants=[
                {"org_id": ORG_A, "slug": "tenant-a-ip", "display_name": "租户A代理所", "admin_id": ADMIN_A,
                 "admin_email": "admin_a@tenant.com", "membership_id": MEMBER_A, "monthly_case_allowance": 2},
                {"org_id": ORG_B, "slug": "tenant-b-ip", "display_name": "租户B代理所", "admin_id": ADMIN_B,
                 "admin_email": "admin_b@tenant.com", "membership_id": MEMBER_B, "monthly_case_allowance": 50},
            ],
        )


@pytest.mark.asyncio
async def test_case_lifecycle_and_quota_enforcement() -> None:
    migration_url = postgres_url("PE_TEST_MIGRATION_DATABASE_URL", "patent_evidence_migration")
    clock = Clock()
    _seed_org_and_identities(migration_url, clock())

    settings = api_settings(mfa_encryption_key=MFA_KEY)
    app = create_app(settings=settings, clock=clock)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        # 1. Login Admin A
        secret_a = await login_with_totp(client, clock=clock, email="admin_a@tenant.com", password=PASSWORD)

        # 2. Create Case 1 in Org A
        res1 = await client.post(
            f"/api/v1/organizations/{ORG_A}/cases",
            json={
                "case_number": "2026-PAT-001",
                "title": "大模型注意力量化方法",
                "technical_field": "计算机软件",
                "target_jurisdiction": "CN",
            },
        )
        assert res1.status_code == 201
        case1 = res1.json()["case"]
        case1_id = case1["id"]
        assert case1["case_number"] == "2026-PAT-001"
        assert case1["status"] == "draft"

        # 3. Create Case 2 in Org A (hits allowance limit of 2)
        res2 = await client.post(
            f"/api/v1/organizations/{ORG_A}/cases",
            json={
                "case_number": "2026-PAT-002",
                "title": "量子纠缠探测装置",
                "technical_field": "量子物理",
            },
        )
        assert res2.status_code == 201

        # 4. Create Case 3 in Org A -> Fails with quota exceeded (422)
        res3 = await client.post(
            f"/api/v1/organizations/{ORG_A}/cases",
            json={
                "case_number": "2026-PAT-003",
                "title": "超出配额的案件",
                "technical_field": "测试",
            },
        )
        assert res3.status_code == 422
        assert "quota_exceeded" in res3.json()["detail"]

        # 5. Duplicate case number in same org -> 409
        # (Login Admin B to test same case number in another org)
        await login_with_totp(client, clock=clock, email="admin_b@tenant.com", password=PASSWORD)
        res_b = await client.post(
            f"/api/v1/organizations/{ORG_B}/cases",
            json={
                "case_number": "2026-PAT-001",  # Same case number, different org
                "title": "租户B同名案号案件",
                "technical_field": "测试",
            },
        )
        assert res_b.status_code == 201
        assert res_b.json()["case"]["organization_id"] == str(ORG_B)

        # 6. Cross-tenant isolation: Admin B cannot read or modify Org A's case
        res_cross = await client.get(f"/api/v1/organizations/{ORG_B}/cases/{case1_id}")
        assert res_cross.status_code == 404

        # 7. Upload document to Case 1
        await login_with_existing_totp(client, clock=clock, email="admin_a@tenant.com", password=PASSWORD, secret=secret_a)

        # Create in-memory docx
        doc = Document()
        doc.add_heading("技术领域", level=1)
        doc.add_paragraph("本技术交底书涉及人工智能大模型技术。")
        doc.add_heading("技术方案", level=1)
        doc.add_paragraph("通过多尺度混合稀疏量化，实现显存降低40%。")
        buf = io.BytesIO()
        doc.save(buf)
        docx_bytes = buf.getvalue()

        upload_res = await client.post(
            f"/api/v1/organizations/{ORG_A}/cases/{case1_id}/documents",
            json={
                "filename": "disclosure.docx",
                "content_base64": base64.b64encode(docx_bytes).decode("ascii"),
                "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
        )
        assert upload_res.status_code == 201
        upload_data = upload_res.json()
        assert upload_data["document"]["filename"] == "disclosure.docx"
        assert upload_data["parse_run"]["status"] == "queued"

        # 8. Run Worker task processing
        worker_engine = create_engine(settings.worker_database_url)
        worker_session_factory = create_worker_session_factory(worker_engine)
        storage = ObjectStorageClient()

        worker = ParseTaskWorker(worker_session_factory, storage, clock=clock)
        did_work = await worker.run_once()
        assert did_work is True
        await worker_engine.dispose()

        # 9. Verify case detail has completed parse run and document version
        case_detail_res = await client.get(f"/api/v1/organizations/{ORG_A}/cases/{case1_id}")
        assert case_detail_res.status_code == 200
        case_detail = case_detail_res.json()
        assert case_detail["parse_run"]["status"] == "completed"
        assert case_detail["document_version"] is not None
        assert case_detail["document_version"]["version_number"] == 1
        assert "本技术交底书涉及" in case_detail["document_version"]["parsed_text"]

        # 10. Confirm document version -> Case status advances to document_ready
        ver_id = case_detail["document_version"]["id"]
        confirm_res = await client.post(
            f"/api/v1/organizations/{ORG_A}/cases/{case1_id}/document-versions/{ver_id}/confirm"
        )
        assert confirm_res.status_code == 200
        assert confirm_res.json()["case_status"] == "document_ready"

        # Final check on case
        final_res = await client.get(f"/api/v1/organizations/{ORG_A}/cases/{case1_id}")
        assert final_res.json()["status"] == "document_ready"
        assert final_res.json()["document_version"]["is_confirmed"] is True

        # 11. Upload inspection (spec §6.2): weaponised or disguised files are
        #     rejected and audited; common active content is accepted and recorded.
        upload_url = f"/api/v1/organizations/{ORG_A}/cases/{case1_id}/documents"

        macro_buf = io.BytesIO()
        source_zip = zipfile.ZipFile(io.BytesIO(docx_bytes))
        with zipfile.ZipFile(macro_buf, "w", zipfile.ZIP_DEFLATED) as macro_zip:
            for info in source_zip.infolist():
                macro_zip.writestr(info.filename, source_zip.read(info.filename))
            macro_zip.writestr("word/vbaProject.bin", b"\xd0\xcf\x11\xe0")
        macro_res = await client.post(
            upload_url,
            json={
                "filename": "macro.docx",
                "content_base64": base64.b64encode(macro_buf.getvalue()).decode("ascii"),
            },
        )
        assert macro_res.status_code == 422
        assert macro_res.json()["detail"] == "macros_not_allowed"

        disguised_res = await client.post(
            upload_url,
            json={
                "filename": "renamed.pdf",
                "content_base64": base64.b64encode(docx_bytes).decode("ascii"),
                "content_type": "application/pdf",
            },
        )
        assert disguised_res.status_code == 422
        assert disguised_res.json()["detail"] == "file_content_does_not_match_extension"

        oversized_res = await client.post(
            upload_url,
            content=b"{}",
            headers={"content-type": "application/json", "content-length": str(64 * 1024 * 1024)},
        )
        assert oversized_res.status_code == 413

        # 客户端声称 text/plain；存储的是按内容判定的 MIME，并记录 PDF JavaScript
        js_writer = PdfWriter()
        js_writer.add_blank_page(width=200, height=200)
        js_writer.add_js("app.alert('x');")
        js_pdf = io.BytesIO()
        js_writer.write(js_pdf)
        js_res = await client.post(
            upload_url, files={"file": ("spec.pdf", js_pdf.getvalue(), "text/plain")}
        )
        assert js_res.status_code == 201
        js_document = js_res.json()["document"]
        assert js_document["mime_type"] == "application/pdf"
        assert js_document["security_findings"] == ["pdf_javascript"]

        latest = (await client.get(f"/api/v1/organizations/{ORG_A}/cases/{case1_id}")).json()
        assert latest["document"]["id"] == js_document["id"]
        assert latest["document"]["security_findings"] == ["pdf_javascript"]

        with psycopg.connect(migration_url) as conn:
            audit_rows = conn.execute(
                """SELECT result, safe_summary FROM audit_events
                WHERE organization_id = %s AND action = 'case.document.upload'
                ORDER BY created_at""",
                (ORG_A,),
            ).fetchall()
            stored = conn.execute(
                "SELECT mime_type, security_findings FROM source_documents WHERE id = %s",
                (UUID(js_document["id"]),),
            ).fetchone()
        results = [row[0] for row in audit_rows]
        assert results.count("denied") >= 2  # macro + disguised
        assert any("findings=pdf_javascript" in row[1] for row in audit_rows if row[0] == "allowed")
        assert stored == ("application/pdf", ["pdf_javascript"])
