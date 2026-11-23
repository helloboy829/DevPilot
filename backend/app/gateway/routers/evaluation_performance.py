"""Frozen performance scenario definition endpoints; no execution endpoints."""

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.performance_run_repository import PerformanceRunRepository
from app.evaluation.performance_scenario_repository import PerformanceScenarioRepository
from app.evaluation.performance_scenarios import PerformanceRunAdmission, PerformanceRunCreate, PerformanceScenarioCreate
from app.evaluation.qa_evidence import EvidenceAccessCreate
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.gateway.authz import require_permission
from app.gateway.private_route import PrivateValidationRoute
from app.gateway.routers.evaluation_projects import _context, _require_human

router = APIRouter(prefix="/api/evaluation/projects", tags=["evaluation-performance"], route_class=PrivateValidationRoute)


def _repo(repository):
    return PerformanceScenarioRepository(repository.sf)


def _run_repo(repository):
    return PerformanceRunRepository(repository.sf)


async def _result(awaitable):
    try:
        return await awaitable
    except NotFound:
        raise HTTPException(404, "Project, component, plan or performance scenario not found") from None
    except Conflict:
        raise HTTPException(409, "Plan or dataset is not eligible, changed or failed integrity validation") from None
    except RequestProtectionError:
        raise HTTPException(503, "Performance evidence is unavailable", headers={"Cache-Control": "private, no-store"}) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Evaluation persistence failed; reload and inspect current state") from None


@router.post("/{project_id}/components/{component_id}/performance-scenarios")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def create_performance_scenario(project_id: str, component_id: str, payload: PerformanceScenarioCreate, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    return await _result(_repo(repository).create(owner, project_id, component_id, payload.plan_id, payload.profile))


@router.get("/{project_id}/components/{component_id}/performance-scenarios")
@require_permission("evaluation_projects", "read")
async def list_performance_scenarios(project_id: str, component_id: str, request: Request):
    owner, repository = await _context(request)
    return {"scenarios": await _result(_repo(repository).list(owner, project_id, component_id))}


@router.get("/{project_id}/performance-scenarios/{scenario_id}")
@require_permission("evaluation_projects", "read")
async def get_performance_scenario(project_id: str, scenario_id: str, request: Request):
    owner, repository = await _context(request)
    return await _result(_repo(repository).get(owner, project_id, scenario_id))


@router.post("/{project_id}/performance-runs")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def create_performance_run(project_id: str, payload: PerformanceRunCreate, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    try:
        return await _run_repo(repository).create_run(
            owner,
            project_id,
            payload.scenario_id,
            payload.scenario_hash,
            confirmed=payload.confirmed,
            run_id=payload.run_id,
        )
    except NotFound:
        raise HTTPException(404, "Project or performance scenario not found") from None
    except Conflict:
        raise HTTPException(409, "Scenario changed or failed integrity validation") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Evaluation persistence failed; reload and inspect current state") from None


@router.post("/{project_id}/performance-runs/{run_id}/admit")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def admit_performance_run(project_id: str, run_id: str, payload: PerformanceRunAdmission, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    try:
        return await _run_repo(repository).admit_run(owner, project_id, run_id, confirmed=payload.confirmed)
    except NotFound:
        raise HTTPException(404, "Project or performance run not found") from None
    except Conflict:
        raise HTTPException(409, "Performance run failed admission or integrity validation") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Evaluation persistence failed; reload and inspect current state") from None


@router.get("/{project_id}/performance-runs")
@require_permission("evaluation_projects", "read")
async def list_performance_runs(
    project_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1, max_length=256),
):
    owner, repository = await _context(request)
    _require_human(request)
    try:
        return await _run_repo(repository).list_runs(owner, project_id, limit=limit, cursor=cursor)
    except NotFound:
        raise HTTPException(404, "Project not found") from None
    except ValueError:
        raise HTTPException(422, "Invalid performance run page") from None
    except Conflict:
        raise HTTPException(409, "Performance run ledger failed integrity validation") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Evaluation persistence failed; reload and inspect current state") from None


@router.get("/{project_id}/performance-runs/{run_id}")
@require_permission("evaluation_projects", "read")
async def get_performance_run(project_id: str, run_id: str, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    try:
        return await _run_repo(repository).get_run(owner, project_id, run_id)
    except NotFound:
        raise HTTPException(404, "Project or performance run not found") from None
    except Conflict:
        raise HTTPException(409, "Performance run ledger failed integrity validation") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Evaluation persistence failed; reload and inspect current state") from None


@router.get("/{project_id}/performance-runs/{run_id}/dispatches")
@require_permission("evaluation_projects", "read")
async def list_performance_dispatches(
    project_id: str,
    run_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0, lt=11_000),
    limit: int = Query(default=100, ge=1, le=200),
):
    owner, repository = await _context(request)
    _require_human(request)
    try:
        dispatches = await _run_repo(repository).list_dispatches(owner, project_id, run_id, offset=offset, limit=limit)
        return {"dispatches": dispatches, "offset": offset, "limit": limit}
    except NotFound:
        raise HTTPException(404, "Project or performance run not found") from None
    except Conflict:
        raise HTTPException(409, "Performance run ledger failed integrity validation") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Evaluation persistence failed; reload and inspect current state") from None


@router.post("/{project_id}/performance-runs/{run_id}/dispatches/{ordinal}/evidence-access")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def create_performance_response_evidence_access(project_id: str, run_id: str, ordinal: int, payload: EvidenceAccessCreate, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    if not 0 <= ordinal < 11_000:
        raise HTTPException(422, "Invalid dispatch ordinal", headers={"Cache-Control": "private, no-store"})
    result = await _result(_run_repo(repository).create_response_evidence_access(owner, project_id, run_id, ordinal, payload))
    return JSONResponse(result, headers={"Cache-Control": "private, no-store"})


@router.get("/{project_id}/performance-evidence/{access_id}")
@require_permission("evaluation_projects", "read")
async def read_performance_response_evidence(project_id: str, access_id: str, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    try:
        result = await _run_repo(repository).read_response_evidence_access(owner, access_id, request.headers.get("range"), project_id=project_id)
    except NotFound:
        raise HTTPException(404, "Performance response evidence not found", headers={"Cache-Control": "private, no-store"}) from None
    except Conflict:
        raise HTTPException(409, "Performance response evidence failed integrity validation", headers={"Cache-Control": "private, no-store"}) from None
    except RequestProtectionError as exc:
        status = 416 if "range" in str(exc).lower() else 503
        raise HTTPException(status, "Performance response evidence is unavailable", headers={"Cache-Control": "private, no-store"}) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Evaluation persistence failed; reload and inspect current state", headers={"Cache-Control": "private, no-store"}) from None
    headers = {"Cache-Control": "private, no-store", "Content-Disposition": 'attachment; filename="performance-response-evidence.bin"'}
    if result["content_range"]:
        headers["Content-Range"] = result["content_range"]
        headers["Accept-Ranges"] = "bytes"
    return Response(content=result["body"], status_code=result["status_code"], media_type="application/octet-stream", headers=headers)
