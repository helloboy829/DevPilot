from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from devpilot.toolkit.report import build_component_test_report
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import (
    get_component_repo,
    get_component_test_run_repo,
    get_component_test_service,
    get_optional_user_from_request,
)

router = APIRouter(prefix="/api", tags=["component-tests"])

ALLOWED_TRANSPORTS = frozenset({"openai_chat", "dify_chat", "dify_workflow", "http_post"})
ALLOWED_RESPONSE_MODES = frozenset({"blocking", "streaming"})
ALLOWED_TEST_TYPES = frozenset({"effect", "perf"})
ALLOWED_VALIDATION_TYPES = frozenset({"reference_text", "manual_review", "reference_values", "field_completeness", "structure"})


class ComponentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    component_code: str | None = None
    transport: str
    api_url: str = Field(min_length=1)
    api_token: str | None = None
    response_mode: str = "blocking"
    supports_streaming: bool = False
    validation_type: str = "reference_text"
    acceptance_criteria: dict[str, Any] = Field(default_factory=dict)


class ComponentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    component_code: str | None = None
    transport: str | None = None
    api_url: str | None = Field(default=None, min_length=1)
    api_token: str | None = None
    response_mode: str | None = None
    supports_streaming: bool | None = None
    validation_type: str | None = None
    acceptance_criteria: dict[str, Any] | None = None
    enabled: bool | None = None


class ComponentTestRunCreateRequest(BaseModel):
    test_type: str
    params: dict[str, Any] = Field(default_factory=dict)


def _validate_create(payload: ComponentCreateRequest) -> None:
    if payload.transport not in ALLOWED_TRANSPORTS:
        raise HTTPException(status_code=422, detail=f"Unsupported transport: {payload.transport}")
    if payload.response_mode not in ALLOWED_RESPONSE_MODES:
        raise HTTPException(status_code=422, detail=f"Unsupported response_mode: {payload.response_mode}")
    if payload.validation_type not in ALLOWED_VALIDATION_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported validation_type: {payload.validation_type}")


@router.get("/component-tests/components")
@require_permission("threads", "read")
async def list_components(request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    repo = get_component_repo(request)
    return {"components": await repo.list_by_user(str(user.id))}


@router.post("/component-tests/components")
@require_permission("threads", "write")
async def create_component(payload: ComponentCreateRequest, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    _validate_create(payload)
    repo = get_component_repo(request)
    component = await repo.create(
        component_id=f"comp-{uuid.uuid4().hex}",
        user_id=str(user.id),
        name=payload.name,
        component_code=payload.component_code,
        transport=payload.transport,
        api_url=payload.api_url,
        api_token=payload.api_token,
        response_mode=payload.response_mode,
        supports_streaming=payload.supports_streaming,
        validation_type=payload.validation_type,
        acceptance_criteria=payload.acceptance_criteria,
    )
    return component


@router.get("/component-tests/components/{component_id}")
@require_permission("threads", "read")
async def get_component(component_id: str, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    component = await get_component_repo(request).get(component_id, user_id=str(user.id))
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return component


@router.patch("/component-tests/components/{component_id}")
@require_permission("threads", "write")
async def update_component(component_id: str, payload: ComponentUpdateRequest, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "transport" in updates and updates["transport"] not in ALLOWED_TRANSPORTS:
        raise HTTPException(status_code=422, detail=f"Unsupported transport: {updates['transport']}")
    if "response_mode" in updates and updates["response_mode"] not in ALLOWED_RESPONSE_MODES:
        raise HTTPException(status_code=422, detail=f"Unsupported response_mode: {updates['response_mode']}")
    if "validation_type" in updates and updates["validation_type"] not in ALLOWED_VALIDATION_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported validation_type: {updates['validation_type']}")
    component = await get_component_repo(request).update(component_id, user_id=str(user.id), updates=updates)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return component


@router.delete("/component-tests/components/{component_id}")
@require_permission("threads", "write")
async def delete_component(component_id: str, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    deleted = await get_component_repo(request).delete(component_id, user_id=str(user.id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Component not found")
    return {"deleted": True}


@router.post("/component-tests/components/{component_id}/runs")
@require_permission("threads", "write")
async def trigger_run(component_id: str, payload: ComponentTestRunCreateRequest, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if payload.test_type not in ALLOWED_TEST_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported test_type: {payload.test_type}")

    user_id = str(user.id)
    component = await get_component_repo(request).get(component_id, user_id=user_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    if component.get("enabled") is False:
        raise HTTPException(status_code=409, detail="Component is disabled")

    run_repo = get_component_test_run_repo(request)
    run = await run_repo.create(
        run_id=f"run-{uuid.uuid4().hex}",
        user_id=user_id,
        component_id=component_id,
        test_type=payload.test_type,
        params=dict(payload.params),
    )
    get_component_test_service(request).enqueue(
        run_id=run["id"],
        user_id=user_id,
        component=component,
        test_type=payload.test_type,
        params=dict(payload.params),
    )
    return run


@router.get("/component-tests/components/{component_id}/runs")
@require_permission("threads", "read")
async def list_component_runs(component_id: str, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"runs": await get_component_test_run_repo(request).list_by_component(component_id, user_id=str(user.id))}


@router.get("/component-tests/runs/{run_id}")
@require_permission("threads", "read")
async def get_run(run_id: str, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    run = await get_component_test_run_repo(request).get(run_id, user_id=str(user.id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/component-tests/runs/{run_id}/report")
@require_permission("threads", "read")
async def get_run_report(run_id: str, request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = str(user.id)
    run_repo = get_component_test_run_repo(request)
    run = await run_repo.get(run_id, user_id=user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    raw_path = run.get("raw_path")
    if raw_path:
        report_path = Path(raw_path).with_name("report.json")
        try:
            data = await asyncio.to_thread(report_path.read_text, encoding="utf-8")
            return json.loads(data)
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError):
            pass

    # 兜底：历史/异常运行缺少落盘报告时，用摘要 + 参数重建一份最小报告。
    component = await get_component_repo(request).get(run["component_id"], user_id=user_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return build_component_test_report(component, test_type=run["test_type"], params=run.get("params") or {})
