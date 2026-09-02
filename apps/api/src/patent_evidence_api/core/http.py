from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, ValidationError

RequestModel = TypeVar("RequestModel", bound=BaseModel)


def parse_uuid_or_404(value: str, *, detail: str = "not_found") -> UUID:
    """Safely parse UUID string or raise HTTP 404."""
    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=detail) from exc


async def parse_json_body(
    request: Request,
    model: type[RequestModel],
    *,
    detail: str = "invalid_request",
) -> RequestModel:
    """Safely validate request JSON body against Pydantic model or raise HTTP 422."""
    try:
        raw_json = await request.json()
        return model.model_validate(raw_json)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=detail) from exc
