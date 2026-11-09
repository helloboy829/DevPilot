"""Human-only narrow grants for independent frozen case review; no project sharing."""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError, RequestProtectionUnavailable
from app.evaluation.review_tasks import ReviewTaskRepository, TaskCommand, TaskCreate, TaskDecision, TaskReopen
from app.gateway.authz import require_permission
from app.gateway.deps import get_local_provider
from app.gateway.private_route import PrivateValidationRoute
from app.gateway.routers.evaluation_projects import _context, _require_human


class ReviewTaskRoute(PrivateValidationRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            headers = {"Cache-Control": "private, no-store"}
            if request.method == "POST":
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 32_000:
                        raise HTTPException(413, "Review request is too large", headers=headers)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            try:
                return await handler(request)
            except NotFound:
                raise HTTPException(404, "Review task or source not found", headers=headers) from None
            except Conflict:
                raise HTTPException(409, "Review state changed or is not eligible; explicitly refresh and review", headers=headers) from None
            except (RequestProtectionError, RequestProtectionUnavailable):
                raise HTTPException(503, "Protected review storage is unavailable or failed integrity checks", headers=headers) from None
            except (JournalWriteUnconfirmed, SQLAlchemyError):
                raise HTTPException(503, "Review write or read could not be confirmed; inspect the same task ID, never automatically resend", headers=headers) from None

        return bounded


router = APIRouter(prefix="/api/evaluation/review-tasks", tags=["independent-review"], route_class=ReviewTaskRoute)
project_router = APIRouter(prefix="/api/evaluation/projects", tags=["independent-review"], route_class=ReviewTaskRoute)


async def _task_context(request):
    actor, repository = await _context(request)
    _require_human(request)
    return actor, ReviewTaskRepository(repository.sf)


@project_router.get("/{project_id}/review-tasks")
@require_permission("evaluation_projects", "read")
async def project_tasks(project_id: str, request: Request, offset: int = Query(0, ge=0, le=10_000), limit: int = Query(100, ge=1, le=200)):
    actor, repo = await _task_context(request)
    return await repo.list_project(actor, project_id, offset=offset, limit=limit)


@project_router.post("/{project_id}/review-tasks/{task_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def create_task(project_id: str, task_id: str, payload: TaskCreate, request: Request):
    actor, repo = await _task_context(request)
    # Check ownership before exact-ID human existence checks; never expose a directory.
    async with repo.sf() as session:
        await repo._project(session, actor, project_id)
    if actor in [*payload.reviewer_ids, payload.arbitrator_id]:
        raise Conflict
    provider = get_local_provider()
    users = await asyncio.gather(*(provider.get_user(key) for key in [*payload.reviewer_ids, payload.arbitrator_id]))
    if any(user is None or user.needs_setup for user in users):
        raise Conflict
    return await repo.create_task(actor, project_id, task_id, payload)


@router.get("")
@require_permission("evaluation_projects", "read")
async def inbox(request: Request, offset: int = Query(0, ge=0, le=10_000), limit: int = Query(100, ge=1, le=200)):
    actor, repo = await _task_context(request)
    return await repo.inbox(actor, offset=offset, limit=limit)


@router.get("/{task_id}")
@require_permission("evaluation_projects", "read")
async def task_metadata(task_id: str, request: Request):
    actor, repo = await _task_context(request)
    return await repo.get_task(actor, task_id)


@router.post("/{task_id}/claim")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def claim(task_id: str, payload: TaskCommand, request: Request):
    actor, repo = await _task_context(request)
    return await repo.claim(actor, task_id, payload)


@router.post("/{task_id}/release")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def release(task_id: str, payload: TaskCommand, request: Request):
    actor, repo = await _task_context(request)
    return await repo.release(actor, task_id, payload)


@router.get("/{task_id}/case")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def open_case(task_id: str, request: Request):
    actor, repo = await _task_context(request)
    return await repo.open_task(actor, task_id)


@router.post("/{task_id}/decisions")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def submit_decision(task_id: str, payload: TaskDecision, request: Request):
    actor, repo = await _task_context(request)
    return await repo.submit_decision(actor, task_id, payload)


@router.get("/{task_id}/result")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def result(task_id: str, request: Request, round_number: int | None = Query(None, ge=1, le=10)):
    actor, repo = await _task_context(request)
    return await repo.get_result(actor, task_id, round_number=round_number)


@router.post("/{task_id}/cancel")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def cancel(task_id: str, payload: TaskCommand, request: Request):
    actor, repo = await _task_context(request)
    return await repo.cancel(actor, task_id, payload)


@router.post("/{task_id}/reopen")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def reopen(task_id: str, payload: TaskReopen, request: Request):
    actor, repo = await _task_context(request)
    return await repo.reopen(actor, task_id, payload)
