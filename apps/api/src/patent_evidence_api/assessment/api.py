"""HTTP routes for pre-assessment versions.

Everything here is read-only or append-only: versions are created, listed and
read; submission and review decisions append decision records. There is no
route that rewrites or deletes a version, because the persistence layer has no
UPDATE/DELETE grant and the approval boundary depends on that.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from modules.assessment.approval import AssessmentApprovalError
from patent_evidence_api.core.http import parse_json_body, parse_uuid_or_404
from patent_evidence_api.organization.access import OrganizationAccess
from patent_evidence_api.assessment.assembly import AssessmentAssemblyService
from patent_evidence_api.assessment.schemas import (
    DISCLAIMER,
    AssessmentCreateBody,
    AssessmentDecideBody,
    render_decision,
    render_version,
    render_version_summary,
)
from patent_evidence_api.assessment.services import AssessmentService


def create_assessment_router(
    access: OrganizationAccess,
    assessment_service: AssessmentService,
    assembly_service: AssessmentAssemblyService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.post("/{organization_id}/cases/{case_id}/assessments", status_code=201)
    async def create_assessment_version(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)
        body = await parse_json_body(request, AssessmentCreateBody)

        async with access.mutation(
            request,
            org_uuid,
            action="case.assessment.create_version",
            target_type="assessment_version",
        ) as operation:
            try:
                record = await assessment_service.create_version(
                    operation.session,
                    organization_id=org_uuid,
                    case_id=case_uuid,
                    payload=body.to_assessment_input(),
                    actor_identity_id=operation.principal.identity_id,
                )
            except AssessmentApprovalError as exc:
                raise HTTPException(status_code=409, detail=exc.code) from exc
            operation.describe(
                target_id=record.id,
                safe_summary=f"Created assessment version {record.version_number}",
            )
            return JSONResponse(
                status_code=201,
                content={"version": render_version(record, status="draft")},
            )

    @router.post("/{organization_id}/cases/{case_id}/assessments/from-case", status_code=201)
    async def create_assessment_version_from_case(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        """从案件既有数据组装评估输入并冻结为新版本。

        源数据缺失不会被填成默认值：缺本案申请日或比对单元格时直接 422，
        不产出版本；其余缺口记入 gaps 并合并为阻塞项。
        """
        if assembly_service is None:
            raise HTTPException(status_code=501, detail="assembly_not_configured")
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.mutation(
            request,
            org_uuid,
            action="case.assessment.create_version_from_case",
            target_type="assessment_version",
        ) as operation:
            assembled = await assembly_service.assemble(
                operation.session, organization_id=org_uuid, case_id=case_uuid
            )
            record = await assessment_service.create_version(
                operation.session,
                organization_id=org_uuid,
                case_id=case_uuid,
                payload=assembled.payload,
                actor_identity_id=operation.principal.identity_id,
                extra_blockers=assembled.gaps,
            )
            operation.describe(
                target_id=record.id,
                safe_summary=f"Assembled assessment version {record.version_number}",
            )
            return JSONResponse(
                status_code=201,
                content={
                    "version": render_version(record, status="draft"),
                    "gaps": list(assembled.gaps),
                    "source": assembled.source,
                },
            )

    @router.get("/{organization_id}/cases/{case_id}/assessments")
    async def list_assessment_versions(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            records = await assessment_service.list_versions(
                session, organization_id=org_uuid, case_id=case_uuid
            )
            return {"items": [render_version_summary(r) for r in records]}

    # 注意：必须注册在 /assessments/{version_number}（int 路径参数）之前，
    # 否则 "delivery-attachment" 会先被 int 路由捕获并因解析失败返回 422。
    @router.get(
        "/{organization_id}/cases/{case_id}/assessments/delivery-attachment"
    )
    async def get_delivery_attachment(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        """为交付包清单挑一个最适合挂接的预评估版本（候选，非结论）。

        只读。返回的 attachment 带 attachable 标记：仅当存在「已批准且无阻塞项」的
        版本时为真；否则回退到最新版本并标 attachable=False 与原因。没有任何评估
        版本时返回 {"attachment": null}。永不声称结论。
        """
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            attachment = await assessment_service.get_delivery_attachment(
                session,
                organization_id=org_uuid,
                case_id=case_uuid,
            )
            if attachment is None:
                return {"attachment": None}
            attachment["requires_human_confirmation"] = bool(
                attachment.get("requires_human_confirmation", True)
            )
            attachment["disclaimer"] = DISCLAIMER
            return {"attachment": attachment}

    @router.get("/{organization_id}/cases/{case_id}/assessments/{version_number}")
    async def get_assessment_version(
        organization_id: str, case_id: str, version_number: int, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            record = await assessment_service.get_version(
                session,
                organization_id=org_uuid,
                case_id=case_uuid,
                version_number=version_number,
            )
            status = await assessment_service.current_status(
                session,
                organization_id=org_uuid,
                case_id=case_uuid,
                version_number=version_number,
            )
            return {"version": render_version(record, status=status)}

    @router.get(
        "/{organization_id}/cases/{case_id}/assessments/{version_number}/input-snapshot"
    )
    async def get_assessment_input_snapshot(
        organization_id: str, case_id: str, version_number: int, request: Request
    ) -> dict[str, Any]:
        """查看某版本冻结时的输入档案快照（本案申请信息 + 各对比文件档案）。

        只读。老版本（输入快照功能上线前创建）没有快照，返回 {"snapshot": null}——
        这是诚实的结果，不是缺陷；绝不从可变档案表回读推断。版本不存在时 404。
        """
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            # 先取版本：不存在时 get_version 抛 404，避免把「无快照」与「无版本」混淆
            await assessment_service.get_version(
                session,
                organization_id=org_uuid,
                case_id=case_uuid,
                version_number=version_number,
            )
            snapshot = await assessment_service.get_input_snapshot(
                session,
                organization_id=org_uuid,
                case_id=case_uuid,
                version_number=version_number,
            )
            return {"snapshot": snapshot}

    @router.get(
        "/{organization_id}/cases/{case_id}/assessments/{version_number}/deliverable"
    )
    async def get_assessment_deliverable(
        organization_id: str, case_id: str, version_number: int, request: Request
    ) -> dict[str, Any]:
        """导出某冻结版本的预评估意见交付物（候选措辞，非结论）。

        与版本路由同为只读；响应携带人工确认标记与免责声明，避免被当成结论。
        """
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            deliverable = await assessment_service.build_deliverable(
                session,
                organization_id=org_uuid,
                case_id=case_uuid,
                version_number=version_number,
            )
            deliverable["requires_human_confirmation"] = bool(
                deliverable.get("requires_human_confirmation", True)
            )
            deliverable["disclaimer"] = DISCLAIMER
            return {"deliverable": deliverable}

    @router.get(
        "/{organization_id}/cases/{case_id}/assessments/{version_number}/diff/{other_version_number}"
    )
    async def diff_assessment_versions(
        organization_id: str,
        case_id: str,
        version_number: int,
        other_version_number: int,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.authorized(request, org_uuid) as (session, _):
            diff = await assessment_service.diff_versions(
                session,
                organization_id=org_uuid,
                case_id=case_uuid,
                from_version=version_number,
                to_version=other_version_number,
            )
            rendered = diff.to_dict()
            # 差异同样不是结论：带上人工确认标记与免责声明，避免 diff 被当成
            # 「阻塞项消失了所以可以出结论」的依据。
            rendered["requires_human_confirmation"] = diff.requires_human_confirmation
            rendered["disclaimer"] = DISCLAIMER
            return {"diff": rendered}

    @router.post("/{organization_id}/cases/{case_id}/assessments/{version_number}/submit")
    async def submit_assessment_version(
        organization_id: str, case_id: str, version_number: int, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)

        async with access.mutation(
            request,
            org_uuid,
            action="case.assessment.submit_version",
            target_type="assessment_version_review",
        ) as operation:
            try:
                record = await assessment_service.submit_version(
                    operation.session,
                    organization_id=org_uuid,
                    case_id=case_uuid,
                    version_number=version_number,
                    actor_identity_id=operation.principal.identity_id,
                )
            except AssessmentApprovalError as exc:
                raise HTTPException(status_code=409, detail=exc.code) from exc
            operation.describe(
                target_id=UUID(record.version_id),
                safe_summary=f"Submitted assessment version {version_number}",
            )
            return {"decision": render_decision(record)}

    @router.post("/{organization_id}/cases/{case_id}/assessments/{version_number}/decide")
    async def decide_assessment_version(
        organization_id: str, case_id: str, version_number: int, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        case_uuid = parse_uuid_or_404(case_id)
        body = await parse_json_body(request, AssessmentDecideBody)

        async with access.mutation(
            request,
            org_uuid,
            action="case.assessment.decide_version",
            target_type="assessment_version_review",
        ) as operation:
            try:
                record = await assessment_service.decide_version(
                    operation.session,
                    organization_id=org_uuid,
                    case_id=case_uuid,
                    version_number=version_number,
                    decision=body.decision,
                    reviewer_identity_id=operation.principal.identity_id,
                    comments=body.comments,
                    accepts_insufficient_evidence=body.accepts_insufficient_evidence,
                )
            except AssessmentApprovalError as exc:
                raise HTTPException(status_code=409, detail=exc.code) from exc
            operation.describe(
                target_id=UUID(record.version_id),
                safe_summary=f"Assessment decision: {body.decision}",
            )
            return {"decision": render_decision(record)}

    return router
