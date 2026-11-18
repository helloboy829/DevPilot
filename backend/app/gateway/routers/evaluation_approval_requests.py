"""Human authenticated signatures scoped to explicitly assigned summaries."""

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.approval_request_service import ApprovalRequestService
from app.evaluation.approval_requests import ApprovalRequestCreate, ApprovalRequestRepository, RequestCommand, SignatureCreate
from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError, RequestProtectionUnavailable
from app.gateway.authz import require_permission
from app.gateway.private_route import PrivateValidationRoute
from app.gateway.routers.evaluation_projects import _approver_account_ready, _context, _require_human


class ApprovalRequestRoute(PrivateValidationRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            headers = {"Cache-Control": "private, no-store"}
            if request.method == "POST":
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 16_384:
                        raise HTTPException(413, "Approval request is too large", headers=headers)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            try:
                return await handler(request)
            except NotFound:
                raise HTTPException(404, "Assigned approval request or source not found", headers=headers) from None
            except Conflict:
                raise HTTPException(409, "Approval state changed or is ineligible; explicitly refresh and review", headers=headers) from None
            except (RequestProtectionError, RequestProtectionUnavailable):
                raise HTTPException(503, "Approval storage is unavailable or failed integrity checks", headers=headers) from None
            except (JournalWriteUnconfirmed, SQLAlchemyError):
                raise HTTPException(503, "Approval operation could not be confirmed; inspect the original request, view or operation ID without resending", headers=headers) from None

        return bounded


router = APIRouter(prefix="/api/evaluation/approval-requests", tags=["assigned-approvals"], route_class=ApprovalRequestRoute)
project_router = APIRouter(prefix="/api/evaluation/projects", tags=["assigned-approvals"], route_class=ApprovalRequestRoute)


async def _signature_context(request):
    actor, repository = await _context(request)
    _require_human(request)
    if request.state.auth.user.needs_setup:
        raise HTTPException(403, "Complete account initialization first", headers={"Cache-Control": "private, no-store"})
    return actor, ApprovalRequestRepository(repository.sf)


@project_router.post("/{project_id}/review-runs/{run_id}/approval-requests/{request_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def create_request(project_id: str, run_id: str, request_id: str, payload: ApprovalRequestCreate, request: Request):
    actor, repo = await _signature_context(request)
    return await ApprovalRequestService(repo, _approver_account_ready).create_request(actor, project_id, run_id, request_id, payload)


@router.get("")
@require_permission("evaluation_projects", "read")
async def inbox(request: Request):
    actor, repo = await _signature_context(request)
    return await repo.inbox(actor)


@router.get("/notifications")
@require_permission("evaluation_projects", "read")
async def notifications(request: Request):
    actor, repo = await _signature_context(request)
    return await repo.notifications(actor)


@router.get("/{request_id}")
@require_permission("evaluation_projects", "read")
async def request_metadata(request_id: str, request: Request):
    actor, repo = await _signature_context(request)
    return await repo.get_request(actor, request_id)


@router.get("/{request_id}/state")
@require_permission("evaluation_projects", "read")
async def request_state(request_id: str, request: Request):
    actor, repo = await _signature_context(request)
    return await repo.request_state(actor, request_id)


@router.get("/{request_id}/operations/{operation_id}")
@require_permission("evaluation_projects", "read")
async def operation_receipt(request_id: str, operation_id: str, request: Request):
    actor, repo = await _signature_context(request)
    return await repo.get_operation(actor, request_id, operation_id)


@router.get("/{request_id}/views/{view_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def summary_view_receipt(request_id: str, view_id: str, request: Request):
    actor, repo = await _signature_context(request)
    return await repo.get_view(actor, request_id, view_id)


@router.post("/{request_id}/views/{view_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def open_summary(request_id: str, view_id: str, payload: RequestCommand, request: Request):
    actor, repo = await _signature_context(request)
    return await repo.open_summary(actor, request_id, view_id, payload)


@router.post("/{request_id}/decisions/{operation_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
async def decide(request_id: str, operation_id: str, payload: SignatureCreate, request: Request):
    actor, repo = await _signature_context(request)
    return await ApprovalRequestService(repo, _approver_account_ready).decide(actor, request_id, operation_id, payload)


@router.post("/{request_id}/cancellations/{operation_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
async def cancel(request_id: str, operation_id: str, payload: RequestCommand, request: Request):
    actor, repo = await _signature_context(request)
    return await repo.cancel(actor, request_id, operation_id, payload)
