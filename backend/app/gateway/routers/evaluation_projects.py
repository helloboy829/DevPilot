"""Private project/data ledger. Authorization is independent from chat permissions."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.datasets import DatasetCreate, DatasetImport, FreezeRequest, ProjectCreate, parse_samples
from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.execution import ExecutionCreate
from app.evaluation.plan_repository import PlanRepository
from app.evaluation.plans import PlanCreate, PlanPreflightError
from app.evaluation.qa_evidence import EvidenceRepository, ReviewCreate
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.registry import ComponentLinkCreate, SubmissionCreate
from app.evaluation.registry_repository import RegistryRepository
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError, RequestProtectionUnavailable
from app.evaluation.request_version_repository import RequestVersionRepository
from app.evaluation.request_versions import RequestVersionCreate
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
            except (RequestProtectionError, RequestProtectionUnavailable):
                raise HTTPException(503, "Protected request storage is unavailable or failed integrity checks; contact the operator", headers={"Cache-Control": "private, no-store"}) from None
            except JournalWriteUnconfirmed:
                raise HTTPException(503, "Evaluation write could not be confirmed; reload and inspect existing state, do not automatically retry", headers={"Cache-Control": "private, no-store"}) from None
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
        raise HTTPException(404, "Project, component, dataset, submission, request version or plan not found") from None
    except PlanPreflightError:
        raise HTTPException(422, "QA request preflight failed; check mapping, sample coverage and budgets") from None
    except Conflict:
        raise HTTPException(409, "Resource changed, is not eligible or already exists; reload and review the current revision") from None


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


@router.get("/{project_id}/component-candidates")
@require_permission("evaluation_projects", "read")
async def component_candidates(project_id: str, request: Request):
    owner, repository = await _context(request)
    return {"components": await _result(RegistryRepository(repository.sf).component_candidates(owner, project_id))}


@router.get("/{project_id}/components")
@require_permission("evaluation_projects", "read")
async def project_components(project_id: str, request: Request):
    owner, repository = await _context(request)
    return {"components": await _result(RegistryRepository(repository.sf).list_project_components(owner, project_id))}


@router.post("/{project_id}/components")
@require_permission("evaluation_projects", "write")
async def link_component(project_id: str, payload: ComponentLinkCreate, request: Request):
    owner, repository = await _context(request)
    return await _result(RegistryRepository(repository.sf).link_component(owner, project_id, payload))


@router.get("/{project_id}/components/{component_id}/submissions")
@require_permission("evaluation_projects", "read")
async def list_submissions(project_id: str, component_id: str, request: Request):
    owner, repository = await _context(request)
    return {"submissions": await _result(RegistryRepository(repository.sf).list_submissions(owner, project_id, component_id))}


@router.post("/{project_id}/components/{component_id}/submissions")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def create_submission(project_id: str, component_id: str, payload: SubmissionCreate, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    return await _result(RegistryRepository(repository.sf).create_submission(owner, project_id, component_id, payload))


@router.get("/{project_id}/submissions/{submission_id}")
@require_permission("evaluation_projects", "read")
async def get_submission(project_id: str, submission_id: str, request: Request):
    owner, repository = await _context(request)
    return await _result(RegistryRepository(repository.sf).get_submission(owner, project_id, submission_id))


@router.get("/{project_id}/registry-audit")
@require_permission("evaluation_projects", "review")
async def registry_audit(project_id: str, request: Request):
    owner, repository = await _context(request)
    return {"events": await _result(RegistryRepository(repository.sf).registry_audit(owner, project_id))}


@router.post("/{project_id}/components/{component_id}/request-versions")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def create_request_version(project_id: str, component_id: str, payload: RequestVersionCreate, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    return await _result(RequestVersionRepository(repository.sf).create_request_version(owner, project_id, component_id, payload))


@router.get("/{project_id}/components/{component_id}/request-versions")
@require_permission("evaluation_projects", "read")
async def list_request_versions(project_id: str, component_id: str, request: Request):
    owner, repository = await _context(request)
    return {"request_versions": await _result(RequestVersionRepository(repository.sf).list_request_versions(owner, project_id, component_id))}


@router.get("/{project_id}/request-versions/{version_id}")
@require_permission("evaluation_projects", "read")
async def get_request_version(project_id: str, version_id: str, request: Request):
    owner, repository = await _context(request)
    return await _result(RequestVersionRepository(repository.sf).get_request_version(owner, project_id, version_id))


@router.get("/{project_id}/request-versions/{version_id}/audit")
@require_permission("evaluation_projects", "review")
async def request_version_audit(project_id: str, version_id: str, request: Request):
    owner, repository = await _context(request)
    return {"events": await _result(RequestVersionRepository(repository.sf).request_version_audit(owner, project_id, version_id))}


@router.post("/{project_id}/components/{component_id}/plans")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def create_plan(project_id: str, component_id: str, payload: PlanCreate, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    return await _result(PlanRepository(repository.sf).create_plan(owner, project_id, component_id, payload))


@router.get("/{project_id}/components/{component_id}/plans")
@require_permission("evaluation_projects", "read")
async def list_plans(project_id: str, component_id: str, request: Request):
    owner, repository = await _context(request)
    return {"plans": await _result(PlanRepository(repository.sf).list_plans(owner, project_id, component_id))}


@router.get("/{project_id}/plans/{plan_id}")
@require_permission("evaluation_projects", "read")
async def get_plan(project_id: str, plan_id: str, request: Request):
    owner, repository = await _context(request)
    return await _result(PlanRepository(repository.sf).get_plan(owner, project_id, plan_id))


@router.get("/{project_id}/plans/{plan_id}/audit")
@require_permission("evaluation_projects", "review")
async def plan_audit(project_id: str, plan_id: str, request: Request):
    owner, repository = await _context(request)
    return {"events": await _result(PlanRepository(repository.sf).plan_audit(owner, project_id, plan_id))}


@router.get("/{project_id}/review-runs")
@require_permission("evaluation_projects", "read")
async def list_review_runs(project_id: str, request: Request):
    owner, repository = await _context(request)
    return {"runs": await _result(EvidenceRepository(repository.sf).list_runs(owner, project_id))}


@router.get("/{project_id}/review-runs/{run_id}/summary")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def get_review_summary(project_id: str, run_id: str, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    return await _result(SummaryRepository(repository.sf).get_summary(owner, project_id, run_id))


@router.get("/{project_id}/review-runs/{run_id}/cases")
@require_permission("evaluation_projects", "read")
async def list_review_cases(project_id: str, run_id: str, request: Request, offset: int = Query(default=0, ge=0, le=10_000), limit: int = Query(default=100, ge=1, le=200)):
    owner, repository = await _context(request)
    return await _result(EvidenceRepository(repository.sf).list_cases(owner, project_id, run_id, offset=offset, limit=limit))


@router.get("/{project_id}/review-runs/{run_id}/cases/{ordinal}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def open_review_case(project_id: str, run_id: str, ordinal: int, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    if not 1 <= ordinal <= 10_000:
        raise HTTPException(422, "Invalid case ordinal")
    return await _result(EvidenceRepository(repository.sf).open_case(owner, project_id, run_id, ordinal))


@router.post("/{project_id}/review-runs/{run_id}/cases/{ordinal}/reviews")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def review_case(project_id: str, run_id: str, ordinal: int, payload: ReviewCreate, request: Request):
    owner, repository = await _context(request)
    _require_human(request)
    if not 1 <= ordinal <= 10_000:
        raise HTTPException(422, "Invalid case ordinal")
    return await _result(EvidenceRepository(repository.sf).review_case(owner, project_id, run_id, ordinal, payload))


async def _execution_context(request, project_id):
    owner, repository = await _context(request)
    async with repository.sf() as session:
        await _result(repository._project(session, owner, project_id))
    execution = getattr(request.app.state, "evaluation_execution_repo", None)
    if execution is None:
        raise HTTPException(503, "Evaluation execution service is unavailable")
    return owner, execution


@router.get("/{project_id}/execution-policy")
@require_permission("evaluation_projects", "read")
async def execution_policy(project_id: str, request: Request):
    _, repository = await _execution_context(request, project_id)
    # Operator-owned, read-only and restart-required. No credentials or target list.
    return {**repository.policy.model_dump(), "scope": "admitted_qa_json", "automatic_retry": False, "streaming": False}


@router.get("/{project_id}/execution-runs")
@require_permission("evaluation_projects", "read")
async def list_executions(project_id: str, request: Request):
    owner, repository = await _execution_context(request, project_id)
    return {"executions": await _result(repository.list_executions(owner, project_id))}


@router.get("/{project_id}/execution-runs/{execution_id}")
@require_permission("evaluation_projects", "read")
async def get_execution(project_id: str, execution_id: str, request: Request):
    owner, repository = await _execution_context(request, project_id)
    return await _result(repository.get_execution(owner, project_id, execution_id))


@router.put("/{project_id}/execution-runs/{execution_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def admit_execution(project_id: str, execution_id: str, payload: ExecutionCreate, request: Request):
    _require_human(request)
    owner, repository = await _execution_context(request, project_id)
    if len(execution_id) != 32 or any(char not in "0123456789abcdef" for char in execution_id):
        raise HTTPException(422, "Invalid execution identifier")
    return await _result(repository.admit(owner, project_id, execution_id, payload))


@router.post("/{project_id}/execution-runs/{execution_id}/cancel")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def cancel_execution(project_id: str, execution_id: str, request: Request):
    _require_human(request)
    owner, repository = await _execution_context(request, project_id)
    return await _result(repository.cancel(owner, project_id, execution_id))
