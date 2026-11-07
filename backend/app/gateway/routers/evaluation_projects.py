"""Private project/data ledger. Authorization is independent from chat permissions."""

import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.datasets import DatasetCreate, DatasetImport, FreezeRequest, ProjectCreate, parse_samples
from app.evaluation.repository import Conflict, NotFound
from app.gateway.authz import _is_internal_caller, require_permission
from app.gateway.deps import get_optional_user_from_request
from app.gateway.private_route import PrivateValidationRoute

logger = logging.getLogger(__name__)


class BoundedDataRoute(PrivateValidationRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            if request.method in {"POST", "PUT"}:
                chunks = []
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 3_100_000:
                        raise HTTPException(413, "Evaluation request is too large", headers={"Cache-Control": "private, no-store"})
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            try:
                return await handler(request)
            except SQLAlchemyError:
                # SQL exception text may contain statement parameters (including gold).
                logger.warning("Evaluation database operation failed; details suppressed")
                raise HTTPException(503, "Evaluation persistence failed; retry or contact the operator", headers={"Cache-Control": "private, no-store"}) from None

        return bounded


router = APIRouter(prefix="/api/evaluation/projects", tags=["evaluation-data"], route_class=BoundedDataRoute)


async def _context(request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    repo = getattr(request.app.state, "evaluation_repo", None)
    if repo is None:
        raise HTTPException(503, "Persistent evaluation database is unavailable")
    return str(user.id), repo


def _require_human(request):
    if _is_internal_caller(request, request.state.auth.user):
        raise HTTPException(403, "Internal agents cannot access reference review or attest human data review")


async def _result(operation):
    try:
        return await operation
    except NotFound:
        raise HTTPException(404, "Project or dataset not found") from None
    except Conflict:
        raise HTTPException(409, "Dataset changed, is empty or frozen; reload and review the current revision") from None


@router.get("")
@require_permission("evaluation_projects", "read")
async def list_projects(request: Request):
    owner, repo = await _context(request)
    return {"projects": await repo.list_projects(owner)}


@router.post("")
@require_permission("evaluation_projects", "write")
async def create_project(payload: ProjectCreate, request: Request):
    owner, repo = await _context(request)
    return await repo.create_project(owner, payload.name)


@router.get("/{project_id}/datasets")
@require_permission("evaluation_projects", "read")
async def list_datasets(project_id: str, request: Request):
    owner, repo = await _context(request)
    return {"datasets": await _result(repo.list_datasets(owner, project_id))}


@router.post("/{project_id}/datasets")
@require_permission("evaluation_projects", "write")
async def create_dataset(project_id: str, payload: DatasetCreate, request: Request):
    owner, repo = await _context(request)
    return await _result(repo.create_dataset(owner, project_id, payload.name, payload.purpose, payload.source))


@router.get("/{project_id}/datasets/{dataset_id}")
@require_permission("evaluation_projects", "read")
async def get_dataset(project_id: str, dataset_id: str, request: Request):
    owner, repo = await _context(request)
    return await _result(repo.get_dataset(owner, project_id, dataset_id))


@router.get("/{project_id}/datasets/{dataset_id}/samples")
@require_permission("evaluation_projects", "read")
async def read_samples(project_id: str, dataset_id: str, request: Request):
    owner, repo = await _context(request)
    return {"samples": await _result(repo.read_samples(owner, project_id, dataset_id))}


@router.get("/{project_id}/datasets/{dataset_id}/references")
@require_permission("evaluation_projects", "review")
async def read_references(project_id: str, dataset_id: str, request: Request):
    owner, repo = await _context(request)
    _require_human(request)
    return {"samples": await _result(repo.read_samples(owner, project_id, dataset_id, references=True))}


@router.put("/{project_id}/datasets/{dataset_id}/samples")
@require_permission("evaluation_projects", "write")
async def import_samples(project_id: str, dataset_id: str, payload: DatasetImport, request: Request):
    owner, repo = await _context(request)
    # Check ownership before parsing potentially expensive imports.
    await _result(repo.get_dataset(owner, project_id, dataset_id))
    try:
        samples = parse_samples(payload)
    except ValueError:
        raise HTTPException(422, "Invalid QA import; check schema, references, duplicates and size limits") from None
    return await _result(repo.replace_samples(owner, project_id, dataset_id, payload.revision, samples))


@router.post("/{project_id}/datasets/{dataset_id}/freeze")
@require_permission("evaluation_projects", "review")
async def freeze_dataset(project_id: str, dataset_id: str, payload: FreezeRequest, request: Request):
    owner, repo = await _context(request)
    _require_human(request)
    return await _result(repo.freeze(owner, project_id, dataset_id, payload.revision, payload.content_hash))


@router.get("/{project_id}/datasets/{dataset_id}/audit")
@require_permission("evaluation_projects", "review")
async def read_audit(project_id: str, dataset_id: str, request: Request):
    owner, repo = await _context(request)
    return {"events": await _result(repo.audit(owner, project_id, dataset_id))}
