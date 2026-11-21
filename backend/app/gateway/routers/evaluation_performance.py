"""Frozen performance scenario definition endpoints; no execution endpoints."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.performance_scenario_repository import PerformanceScenarioRepository
from app.evaluation.performance_scenarios import PerformanceScenarioCreate
from app.evaluation.repository import Conflict, NotFound
from app.gateway.authz import require_permission
from app.gateway.private_route import PrivateValidationRoute
from app.gateway.routers.evaluation_projects import _context, _require_human

router = APIRouter(prefix="/api/evaluation/projects", tags=["evaluation-performance"], route_class=PrivateValidationRoute)


def _repo(repository):
    return PerformanceScenarioRepository(repository.sf)


async def _result(awaitable):
    try:
        return await awaitable
    except NotFound:
        raise HTTPException(404, "Project, component, plan or performance scenario not found") from None
    except Conflict:
        raise HTTPException(409, "Plan or dataset is not eligible, changed or failed integrity validation") from None
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
