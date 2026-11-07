"""User-owned scheduled evaluation plans; no chat prompts or delivery channels."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from devpilot.http import RequestSpec
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.http import resolve_destination
from app.evaluation.schedules import ASSISTANT_ID, freeze_plan
from app.gateway.authz import require_permission
from app.gateway.deps import get_component_repo, get_config, get_optional_user_from_request, get_scheduled_task_repo
from app.gateway.private_route import PrivateValidationRoute
from deerflow.scheduler.schedules import next_run_at, normalize_cron_expression, validate_timezone

router = APIRouter(route_class=PrivateValidationRoute, prefix="/api/evaluation-schedules", tags=["scheduled-evaluations"])


class EvaluationScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)
    component_id: str = Field(min_length=1, max_length=100)
    test_type: Literal["effect", "perf"]
    params: dict[str, Any]
    schedule_type: Literal["once", "cron"]
    schedule_spec: dict[str, Any] = Field(max_length=2)
    timezone: str = Field(min_length=1, max_length=100)
    consent: Literal[True]


@router.get("")
@require_permission("threads", "read")
async def list_evaluation_schedules(request: Request, config=Depends(get_config)):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    rows = await get_scheduled_task_repo(request).list_by_user(str(user.id))
    tasks = []
    for row in rows:
        if row.get("assistant_id") == ASSISTANT_ID:
            try:
                plan = json.loads(row["prompt"])
            except (ValueError, TypeError, OSError, TimeoutError):
                plan = {"invalid": True}
            tasks.append({k: v for k, v in row.items() if k != "prompt"} | {"plan": plan})
    return JSONResponse({"enabled": config.scheduler.enabled, "tasks": tasks}, headers={"Cache-Control": "private, no-store"})


@router.post("")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def create_evaluation_schedule(payload: EvaluationScheduleCreate, request: Request, config=Depends(get_config)):
    if not config.scheduler.enabled:
        raise HTTPException(409, "Operator must enable scheduler.enabled before scheduling evaluations")
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    component = await get_component_repo(request).get(payload.component_id, user_id=str(user.id))
    if component is None:
        raise HTTPException(404, "Component not found")
    try:
        plan = freeze_plan(component, payload.test_type, payload.params)
        validate_timezone(payload.timezone)
        spec = dict(payload.schedule_spec)
        if payload.schedule_type == "cron":
            spec = {"cron": normalize_cron_expression(spec.get("cron", ""))}
        now = datetime.now(UTC)
        due = next_run_at(payload.schedule_type, spec, payload.timezone, now=now)
        if due is None or (payload.schedule_type == "once" and (due - now).total_seconds() < config.scheduler.min_once_delay_seconds):
            raise ValueError("Choose a valid future schedule, beyond the minimum delay")
        await resolve_destination(RequestSpec(url=component["api_url"]), config)
    except (ValueError, TypeError, OSError, TimeoutError):
        raise HTTPException(422, "Invalid schedule, test plan, or destination not approved by outbound policy") from None
    row = await get_scheduled_task_repo(request).create(
        task_id="task-" + uuid.uuid4().hex,
        user_id=str(user.id),
        thread_id=None,
        context_mode="fresh_thread_per_run",
        assistant_id=ASSISTANT_ID,
        title=payload.title,
        prompt=json.dumps(plan, ensure_ascii=False),
        schedule_type=payload.schedule_type,
        schedule_spec=spec,
        timezone=payload.timezone,
        next_run_at=due,
    )
    return JSONResponse({k: v for k, v in row.items() if k != "prompt"} | {"plan": plan}, headers={"Cache-Control": "private, no-store"})
