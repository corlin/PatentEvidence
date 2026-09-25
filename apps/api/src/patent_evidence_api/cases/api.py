from __future__ import annotations

import base64

from typing import Any, TypeVar
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from adapters.object_storage.client import ObjectStorageClient
from modules.cases.upload_guard import MAX_FILE_SIZE
from patent_evidence_api.cases.services import CaseService, DocumentService, DrawingService
from patent_evidence_api.core.http import parse_json_body, parse_uuid_or_404
from patent_evidence_api.organization.access import OrganizationAccess


# 请求体上限：base64 JSON 膨胀约 4/3，另留 1 MB 给 multipart 边界与 JSON 包装
MAX_UPLOAD_REQUEST_BYTES = MAX_FILE_SIZE * 4 // 3 + 1024 * 1024


class CaseCreateBody(BaseModel):
    case_number: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    technical_field: str = Field(min_length=1, max_length=128)
    target_jurisdiction: str = Field(default="CN", min_length=2, max_length=32)


class DirectUploadBody(BaseModel):
    filename: str
    content_base64: str | None = None
    content_text: str | None = None
    content_type: str = "application/octet-stream"


class DrawingUpdateBody(BaseModel):
    figure_label: str | None = None
    figure_title: str | None = None
    reference_marks: list[dict[str, str]] | None = None
    order_index: int | None = None


class DrawingCreateBody(BaseModel):
    filename: str
    figure_label: str = "附图"
    figure_title: str = ""
    reference_marks: list[dict[str, str]] = Field(default_factory=list)
    content_base64: str | None = None
    mime_type: str = "image/png"


def create_cases_router(
    access: OrganizationAccess,
    case_service: CaseService,
    document_service: DocumentService,
    storage: ObjectStorageClient,
    drawing_service: DrawingService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/organizations")

    @router.post("/{organization_id}/cases", status_code=201)
    async def create_case(organization_id: str, request: Request) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.create",
            target_type="case",
        ) as operation:
            body = await parse_json_body(request, CaseCreateBody)
            case_data = await case_service.create_case(
                operation.session,
                organization_id=org_uuid,
                actor_identity_id=operation.principal.identity_id,
                case_number=body.case_number,
                title=body.title,
                technical_field=body.technical_field,
                target_jurisdiction=body.target_jurisdiction,
            )
            operation.describe(
                target_id=UUID(case_data["id"]),
                safe_summary=f"Created case {body.case_number}",
            )
        return JSONResponse(status_code=201, content={"case": case_data})

    @router.get("/{organization_id}/cases")
    async def list_cases(organization_id: str, request: Request) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        async with access.authorized(request, org_uuid) as (session, _):
            return {"items": await case_service.list_cases(session, org_uuid)}

    @router.get("/{organization_id}/cases/{case_id}")
    async def get_case(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            detail = await case_service.get_case(session, org_uuid, c_uuid)
            if detail is None:
                raise HTTPException(status_code=404, detail="case_not_found")
            return detail

    @router.post("/{organization_id}/cases/{case_id}/documents", status_code=201)
    async def upload_document(
        organization_id: str,
        case_id: str,
        request: Request,
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)

        # 在鉴权前读取请求体，因此先按声明长度设上限，避免把超大请求整体读入内存
        declared_length = request.headers.get("content-length")
        if declared_length is None or not declared_length.isdigit():
            raise HTTPException(status_code=411, detail="content_length_required")
        if int(declared_length) > MAX_UPLOAD_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="file_size_exceeds_30mb_limit")

        # Handle both multipart and JSON base64 payloads. The client-declared
        # Content-Type is ignored: the service decides the type from the bytes.
        content_type_header = request.headers.get("content-type", "")
        filename = "document.docx"
        file_bytes = b""

        if "multipart/form-data" in content_type_header:
            form = await request.form(max_files=1, max_fields=5)
            upload_file = form.get("file")
            if upload_file is None or not hasattr(upload_file, "read"):
                raise HTTPException(status_code=422, detail="missing_file_in_form")
            filename = getattr(upload_file, "filename", None) or "document.docx"
            # 多读 1 字节即可判定超限，不必读完整个文件
            file_bytes = await upload_file.read(MAX_FILE_SIZE + 1)
        else:
            try:
                body = DirectUploadBody.model_validate(await request.json())
                filename = body.filename
                if body.content_base64:
                    file_bytes = base64.b64decode(body.content_base64, validate=True)
                elif body.content_text:
                    file_bytes = body.content_text.encode("utf-8")
                else:
                    raise HTTPException(status_code=422, detail="missing_file_content")
            except Exception as exc:
                if isinstance(exc, HTTPException):
                    raise exc
                raise HTTPException(status_code=422, detail="invalid_upload_body") from exc

        async with access.mutation(
            request,
            org_uuid,
            action="case.document.upload",
            target_type="source_document",
        ) as operation:
            # First ensure case exists
            existing_case = await case_service.get_case(operation.session, org_uuid, c_uuid)
            if existing_case is None:
                raise HTTPException(status_code=404, detail="case_not_found")

            upload_result = await document_service.upload_document(
                operation.session,
                storage,
                organization_id=org_uuid,
                case_id=c_uuid,
                filename=filename,
                data=file_bytes,
            )
            operation.describe(
                target_id=UUID(upload_result["document"]["id"]),
                safe_summary=(
                    f"Uploaded source document {filename}"
                    + (
                        f" findings={','.join(upload_result['document']['security_findings'])}"
                        if upload_result["document"]["security_findings"]
                        else ""
                    )
                ),
            )

        return JSONResponse(status_code=201, content=upload_result)

    @router.get("/{organization_id}/cases/{case_id}/document-versions")
    async def list_document_versions(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        async with access.authorized(request, org_uuid) as (session, _):
            return {
                "items": await document_service.list_versions(
                    session, org_uuid, c_uuid
                )
            }

    @router.post(
        "/{organization_id}/cases/{case_id}/document-versions/{version_id}/confirm"
    )
    async def confirm_document_version(
        organization_id: str,
        case_id: str,
        version_id: str,
        request: Request,
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        v_uuid = parse_uuid_or_404(version_id)
        async with access.mutation(
            request,
            org_uuid,
            action="case.document_version.confirm",
            target_type="document_version",
            target_id=v_uuid,
        ) as operation:
            result = await case_service.confirm_document_version(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                version_id=v_uuid,
                actor_identity_id=operation.principal.identity_id,
            )
            operation.describe(
                target_id=v_uuid,
                safe_summary="Confirmed case document version",
            )
            return result

    # --- Case Drawings Endpoints ---

    @router.get("/{organization_id}/cases/{case_id}/drawings")
    async def list_case_drawings(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        ds = drawing_service or DrawingService(lambda: access._clock())
        async with access.authorized(request, org_uuid) as (session, _):
            return {
                "items": await ds.list_drawings(session, org_uuid, c_uuid)
            }

    @router.post("/{organization_id}/cases/{case_id}/drawings", status_code=201)
    async def create_case_drawing(
        organization_id: str, case_id: str, request: Request
    ) -> JSONResponse:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        ds = drawing_service or DrawingService(lambda: access._clock())

        content_type_header = request.headers.get("content-type", "")
        file_bytes = b""
        filename = "drawing.png"
        mime = "image/png"
        figure_label = "附图"
        figure_title = ""
        reference_marks: list[dict[str, str]] = []

        if "multipart/form-data" in content_type_header:
            form = await request.form()
            upload_file = form.get("file")
            if upload_file is None or not hasattr(upload_file, "read"):
                raise HTTPException(status_code=422, detail="missing_file_in_form")
            filename = getattr(upload_file, "filename", None) or "drawing.png"
            mime = getattr(upload_file, "content_type", None) or "image/png"
            file_bytes = await upload_file.read()
            figure_label = str(form.get("figure_label") or "附图")
            figure_title = str(form.get("figure_title") or "")
            raw_marks = form.get("reference_marks")
            if raw_marks and isinstance(raw_marks, str):
                try:
                    import json
                    reference_marks = json.loads(raw_marks)
                except Exception:
                    reference_marks = []
        else:
            body = await parse_json_body(request, DrawingCreateBody)
            filename = body.filename
            mime = body.mime_type
            figure_label = body.figure_label
            figure_title = body.figure_title
            reference_marks = body.reference_marks
            if body.content_base64:
                import base64
                file_bytes = base64.b64decode(body.content_base64)
            else:
                raise HTTPException(status_code=422, detail="missing_image_content")

        async with access.mutation(
            request,
            org_uuid,
            action="case.drawing.create",
            target_type="case_drawing",
        ) as operation:
            result = await ds.add_drawing(
                operation.session,
                storage,
                organization_id=org_uuid,
                case_id=c_uuid,
                data=file_bytes,
                filename=filename,
                figure_label=figure_label,
                figure_title=figure_title,
                reference_marks=reference_marks,
                mime_type=mime,
            )
            operation.describe(
                target_id=UUID(result["id"]),
                safe_summary=f"Added drawing {figure_label}",
            )
            return JSONResponse(status_code=201, content={"drawing": result})

    @router.patch("/{organization_id}/cases/{case_id}/drawings/{drawing_id}")
    async def update_case_drawing(
        organization_id: str, case_id: str, drawing_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        d_uuid = parse_uuid_or_404(drawing_id)
        ds = drawing_service or DrawingService(lambda: access._clock())

        body = await parse_json_body(request, DrawingUpdateBody)
        async with access.mutation(
            request,
            org_uuid,
            action="case.drawing.update",
            target_type="case_drawing",
            target_id=d_uuid,
        ) as operation:
            result = await ds.update_drawing_metadata(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                drawing_id=d_uuid,
                figure_label=body.figure_label,
                figure_title=body.figure_title,
                reference_marks=body.reference_marks,
                order_index=body.order_index,
            )
            operation.describe(
                target_id=d_uuid,
                safe_summary=f"Updated drawing {result['figure_label']}",
            )
            return {"drawing": result}

    @router.delete("/{organization_id}/cases/{case_id}/drawings/{drawing_id}", status_code=204)
    async def delete_case_drawing(
        organization_id: str, case_id: str, drawing_id: str, request: Request
    ) -> Response:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        d_uuid = parse_uuid_or_404(drawing_id)
        ds = drawing_service or DrawingService(lambda: access._clock())

        async with access.mutation(
            request,
            org_uuid,
            action="case.drawing.delete",
            target_type="case_drawing",
            target_id=d_uuid,
        ) as operation:
            await ds.delete_drawing(
                operation.session,
                organization_id=org_uuid,
                case_id=c_uuid,
                drawing_id=d_uuid,
            )
            operation.describe(
                target_id=d_uuid,
                safe_summary="Deleted case drawing",
            )
        return Response(status_code=204)

    @router.post("/{organization_id}/cases/{case_id}/drawings/re-extract")
    async def re_extract_case_drawings(
        organization_id: str, case_id: str, request: Request
    ) -> dict[str, Any]:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        ds = drawing_service or DrawingService(lambda: access._clock())

        async with access.mutation(
            request,
            org_uuid,
            action="case.drawings.re_extract",
            target_type="case",
            target_id=c_uuid,
        ) as operation:
            items = await ds.re_extract_drawings(
                operation.session,
                storage,
                organization_id=org_uuid,
                case_id=c_uuid,
            )
            operation.describe(
                target_id=c_uuid,
                safe_summary="Re-extracted case drawings from documents",
            )
            return {"items": items}

    @router.get("/{organization_id}/cases/{case_id}/drawings/{drawing_id}/file")
    async def get_case_drawing_file(
        organization_id: str, case_id: str, drawing_id: str, request: Request
    ) -> Response:
        org_uuid = parse_uuid_or_404(organization_id)
        c_uuid = parse_uuid_or_404(case_id)
        d_uuid = parse_uuid_or_404(drawing_id)
        ds = drawing_service or DrawingService(lambda: access._clock())

        async with access.authorized(request, org_uuid) as (session, _):
            drawing = await ds.get_drawing(session, org_uuid, c_uuid, d_uuid)
            if drawing is None:
                raise HTTPException(status_code=404, detail="drawing_not_found")
            raw_bytes = await storage.get_object(drawing["storage_key"])
            if raw_bytes is None:
                raise HTTPException(status_code=404, detail="drawing_file_not_found")
            return Response(
                content=raw_bytes,
                media_type=drawing["mime_type"],
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable",
                    "Content-Disposition": f'inline; filename="{drawing["sha256"]}.png"',
                },
            )

    return router
