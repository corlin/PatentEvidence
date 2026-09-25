from __future__ import annotations

import hashlib
from datetime import datetime
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from modules.reports.docx_export import ReportProvenance, markdown_to_docx_bytes
from modules.reports.pdf_export import markdown_to_pdf_bytes
from patent_evidence_api.core.http import parse_uuid_or_404
from patent_evidence_api.organization.access import OrganizationAccess
from patent_evidence_api.reports.services import EvidenceReportService


def create_reports_router(
    access: OrganizationAccess,
    report_service: EvidenceReportService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.post(
        "/{organization_id}/cases/{case_id}/evidence/seal",
        status_code=201,
    )
    async def seal_evidence_snapshot(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.evidence.seal",
            target_type="evidence_snapshot",
        ) as operation:
            result = await report_service.seal_evidence_snapshot(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
                actor_email=operation.principal.email,
            )
            operation.describe(
                target_id=UUID(result["snapshot"]["id"]),
                safe_summary="Sealed tamper-evident case evidence snapshot",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get("/{organization_id}/cases/{case_id}/evidence/active")
    async def get_active_evidence_snapshot(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            snapshot_data = await report_service.get_active_snapshot(
                session, org_uuid, c_uuid
            )
            if not snapshot_data:
                raise HTTPException(status_code=404, detail="no_evidence_snapshot_found")
            return snapshot_data

    @router.post("/{organization_id}/cases/{case_id}/reports/generate")
    async def generate_report(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.report.generate",
            target_type="analysis_report",
        ) as operation:
            result = await report_service.seal_evidence_snapshot(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                actor_identity_id=operation.principal.identity_id,
                actor_email=operation.principal.email,
            )
            operation.describe(
                target_id=UUID(result["snapshot"]["id"]),
                safe_summary="Generated and archived patent analysis report",
            )
            return JSONResponse(status_code=201, content=result)

    @router.get("/{organization_id}/cases/{case_id}/reports/active")
    async def get_active_report(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            snapshot_data = await report_service.get_active_snapshot(
                session, org_uuid, c_uuid
            )
            if not snapshot_data or not snapshot_data.get("report"):
                raise HTTPException(status_code=404, detail="no_report_found")
            return snapshot_data

    async def _export_active_report(
        organization_id: str,
        case_id: str,
        request: Request,
        *,
        fmt: str,
        render: Callable[..., bytes],
        media_type: str,
        filename: str,
    ) -> Response:
        """导出当前生效报告的共用路径：取封存快照 → 渲染 → 计算文件哈希 → 审计。

        只读：渲染的是已封存的 Markdown 内容本身，导出器不新增任何措辞，
        报告内的结论门禁结果与免责声明随内容原样携带。页脚写入快照版本号与
        根校验值；文件字节对同一快照是确定的，其 SHA-256 经响应头返回并写入
        审计记录，使交付出去的文件可被核验。
        """
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.mutation(
            request,
            org_uuid,
            action=f"case.report.export_{fmt}",
            target_type="evidence_snapshot",
        ) as operation:
            snapshot_data = await report_service.get_active_snapshot(
                operation.session, org_uuid, c_uuid
            )
            if not snapshot_data or not snapshot_data.get("report"):
                raise HTTPException(status_code=404, detail="no_report_found")
            snapshot = snapshot_data["snapshot"]
            report = snapshot_data["report"]
            provenance = ReportProvenance(
                snapshot_number=snapshot["snapshot_number"],
                root_sha256=snapshot["root_sha256"],
                sealed_at=datetime.fromisoformat(snapshot["sealed_at"]),
            )
            # 渲染是 CPU 密集的同步调用（PDF 约数百毫秒），放到线程池避免阻塞事件循环
            file_bytes = await run_in_threadpool(
                render,
                report["content"] or "",
                title=report["title"] or "专利证据分析报告",
                provenance=provenance,
            )
            file_sha256 = hashlib.sha256(file_bytes).hexdigest()
            operation.describe(
                target_id=UUID(snapshot["id"]),
                safe_summary=(
                    f"Exported report {fmt.upper()} for snapshot "
                    f"#{provenance.snapshot_number} file_sha256={file_sha256}"
                ),
            )
            return Response(
                content=file_bytes,
                media_type=media_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "X-Content-SHA256": file_sha256,
                    "X-Snapshot-Root-SHA256": provenance.root_sha256,
                },
            )

    @router.get("/{organization_id}/cases/{case_id}/reports/active/export.docx")
    async def export_active_report_docx(
        organization_id: str, case_id: str, request: Request
    ) -> Response:
        """把当前生效报告导出为 DOCX（spec 要求的交付格式之一）。"""
        return await _export_active_report(
            organization_id,
            case_id,
            request,
            fmt="docx",
            render=markdown_to_docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="analysis-report.docx",
        )

    @router.get("/{organization_id}/cases/{case_id}/reports/active/export.pdf")
    async def export_active_report_pdf(
        organization_id: str, case_id: str, request: Request
    ) -> Response:
        """把当前生效报告导出为 PDF（spec 要求的交付格式之一）。"""
        return await _export_active_report(
            organization_id,
            case_id,
            request,
            fmt="pdf",
            render=markdown_to_pdf_bytes,
            media_type="application/pdf",
            filename="analysis-report.pdf",
        )

    return router
