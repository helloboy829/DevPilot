"""Authenticated, stateless previews. No report publication or template uploads."""

from datetime import UTC, datetime
from typing import Any

from devpilot.reporting import ReportFacts, ReportValidationError, build_preview, get_template, list_templates
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_optional_user_from_request

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=40)
    facts: dict[str, Any] = Field(max_length=20)


@router.get("/templates")
@require_permission("threads", "read")
async def report_templates(request: Request):
    return JSONResponse({"templates": list_templates()}, headers={"Cache-Control": "private, no-store"})


@router.post("/preview")
@require_permission("threads", "write")
async def report_preview(payload: ReportPreviewRequest, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        template = get_template(payload.template_id, payload.template_version)
        facts = ReportFacts.from_dict(payload.facts)
        result = build_preview(facts, template=template, generated_by=str(user.id), generated_at=datetime.now(UTC).isoformat())
    except ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc), headers={"Cache-Control": "private, no-store"}) from exc
    return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
