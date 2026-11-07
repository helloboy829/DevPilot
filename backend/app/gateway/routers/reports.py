"""Authenticated, stateless previews. No report publication or template uploads."""

from datetime import UTC, datetime
from typing import Any

from devpilot.reporting import ReportAdvisory, ReportFacts, ReportValidationError, build_preview, get_template, list_templates
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_config, get_optional_user_from_request
from app.gateway.private_route import PrivateValidationRoute
from app.reporting import assistant
from app.reporting.intake_contract import IntakeContext

router = APIRouter(route_class=PrivateValidationRoute, prefix="/api/reports", tags=["reports"])


class ReportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=40)
    facts: dict[str, Any] = Field(max_length=20)


class PreviewWithAdvisory(ReportPreviewRequest):
    advisory: dict[str, Any] | None = Field(default=None, max_length=9)


class AssistantRequest(ReportPreviewRequest):
    consent: bool


@router.get("/assistant")
@require_permission("threads", "read")
async def report_assistant_status(request: Request, config=Depends(get_config)):
    return JSONResponse(assistant.get_status(config), headers={"Cache-Control": "private, no-store"})


@router.post("/assistant")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def report_assistant(payload: AssistantRequest, request: Request, config=Depends(get_config)):
    headers = {"Cache-Control": "private, no-store"}
    if payload.consent is not True:
        raise HTTPException(status_code=422, detail="Explicit consent is required to send aggregate metrics to the configured model", headers=headers)
    try:
        template = get_template(payload.template_id, payload.template_version)
        facts = ReportFacts.from_dict(payload.facts)
    except ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc), headers=headers) from exc
    status = assistant.get_status(config)
    if not status["available"]:
        raise HTTPException(status_code=503, detail="Report assistant is not configured or enabled", headers=headers)
    try:
        result = await assistant.run_report_assistant(config, facts, template)
    except assistant.AssistantUnavailable as exc:
        reason = str(exc)
        code = {"busy": 429, "timeout": 504, "provider_error": 502, "invalid_response": 502}.get(reason, 503)
        if reason == "busy":
            headers["Retry-After"] = "5"
        raise HTTPException(status_code=code, detail="Report assistant unavailable: " + reason, headers=headers) from None
    return JSONResponse(result, headers=headers)


@router.get("/templates")
@require_permission("threads", "read")
async def report_templates(request: Request):
    return JSONResponse({"templates": list_templates()}, headers={"Cache-Control": "private, no-store"})


@router.post("/preview")
@require_permission("threads", "write")
async def report_preview(payload: PreviewWithAdvisory, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        template = get_template(payload.template_id, payload.template_version)
        facts = ReportFacts.from_dict(payload.facts)
        result = build_preview(facts, template=template, generated_by=str(user.id), generated_at=datetime.now(UTC).isoformat(), advisory=ReportAdvisory.from_dict(payload.advisory) if payload.advisory is not None else None)
    except ReportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc), headers={"Cache-Control": "private, no-store"}) from exc
    return JSONResponse(result, headers={"Cache-Control": "private, no-store"})


class ProjectPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    template_id: str = Field(min_length=1, max_length=100)
    template_version: str = Field(min_length=1, max_length=40)
    components: list[dict[str, Any]] = Field(min_length=1, max_length=30)


class IntakeRequest(IntakeContext):
    language: str = Field(pattern="^(zh|en)$")
    consent: bool


@router.get("/project/templates")
@require_permission("threads", "read")
async def project_template_catalog(request: Request):
    from devpilot.reporting.project import project_templates

    return JSONResponse({"templates": project_templates()}, headers={"Cache-Control": "private, no-store"})


@router.post("/project/preview")
@require_permission("threads", "write")
async def project_preview(payload: ProjectPreviewRequest, request: Request):
    from devpilot.reporting.project import build_project_preview

    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    try:
        result = build_project_preview(payload.components, payload.template_id, payload.template_version, generated_by=str(user.id), generated_at=datetime.now(UTC).isoformat())
        return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
    except ReportValidationError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/project/intake")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def report_intake(payload: IntakeRequest, request: Request, config=Depends(get_config)):
    from app.reporting.intake import propose_fields

    if payload.consent is not True:
        raise HTTPException(422, "Consent is required to send the entered requirements to the configured model")
    try:
        return JSONResponse(await propose_fields(config, payload.message, payload.language, history=payload.history), headers={"Cache-Control": "private, no-store"})
    except assistant.AssistantUnavailable as exc:
        code = {"busy": 429, "timeout": 504, "provider_error": 502, "invalid_response": 502}.get(str(exc), 503)
        raise HTTPException(code, "Report requirements assistant unavailable: " + str(exc)) from None
