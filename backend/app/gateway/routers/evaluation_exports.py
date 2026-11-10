"""Human-only configuration export; no software/target execution or approval."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.authorized_exports import ExportCreate, ExportUnavailable
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError, RequestProtectionUnavailable
from app.gateway.authz import require_permission
from app.gateway.private_route import PrivateValidationRoute
from app.gateway.routers.evaluation_projects import _context, _require_human


class ExportRoute(PrivateValidationRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            try:
                if request.method == "PUT":
                    chunks, size = [], 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 16_384:
                            raise HTTPException(413, "Export request is too large", headers={"Cache-Control": "private, no-store"})
                        chunks.append(chunk)
                    request._body = b"".join(chunks)
                return await handler(request)
            except NotFound:
                raise HTTPException(404, "Export or source not found", headers={"Cache-Control": "private, no-store"}) from None
            except Conflict:
                raise HTTPException(409, "Export exists or source changed; reconcile only by GET of the same export ID, never resend PUT", headers={"Cache-Control": "private, no-store"}) from None
            except (ExportUnavailable, RequestProtectionError, RequestProtectionUnavailable, SQLAlchemyError):
                raise HTTPException(503, "Export unavailable or write outcome unknown; inspect only the same export ID by GET, never automatically resend PUT", headers={"Cache-Control": "private, no-store"}) from None

        return bounded


router = APIRouter(prefix="/api/evaluation/projects", tags=["evaluation-exports"], route_class=ExportRoute)


async def _repository(request):
    owner, _ = await _context(request)
    _require_human(request)
    repo = getattr(request.app.state, "evaluation_export_repo", None)
    if repo is None:
        raise HTTPException(503, "Export service unavailable")
    return owner, repo


@router.get("/{project_id}/export-capabilities")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_exports", "read")
async def export_capabilities(project_id: str, request: Request):
    owner, repo = await _repository(request)
    return await repo.capabilities(owner, project_id)


@router.put("/{project_id}/exports/{export_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_exports", "create")
async def create_export(project_id: str, export_id: str, payload: ExportCreate, request: Request):
    owner, repo = await _repository(request)
    if len(export_id) != 32 or any(c not in "0123456789abcdef" for c in export_id):
        raise HTTPException(422, "Invalid export identifier")
    return await repo.create(owner, project_id, export_id, payload)


@router.get("/{project_id}/exports/{export_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_exports", "read")
async def get_export(project_id: str, export_id: str, request: Request):
    owner, repo = await _repository(request)
    if len(export_id) != 32 or any(c not in "0123456789abcdef" for c in export_id):
        raise HTTPException(422, "Invalid export identifier")
    return await repo.get(owner, project_id, export_id)


@router.get("/{project_id}/exports/{export_id}/bundle")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "review")
@require_permission("evaluation_exports", "download")
async def download_export(project_id: str, export_id: str, request: Request, viewed_receipt_hash: str = Query(pattern=r"^[0-9a-f]{64}$"), confirm_download: Literal["true"] = Query()):
    owner, repo = await _repository(request)
    if len(export_id) != 32 or any(c not in "0123456789abcdef" for c in export_id):
        raise HTTPException(422, "Invalid export identifier")
    data = await repo.open_bundle(owner, project_id, export_id, viewed_receipt_hash)
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="qa-config-' + export_id + '.zip"', "X-Content-Type-Options": "nosniff", "X-DevPilot-Exporter": "platform-local-qa-config.v1", "X-DevPilot-Receipt-Hash": viewed_receipt_hash},
    )


@router.get("/{project_id}/exports/{export_id}/audit")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_exports", "read")
async def export_audit(project_id: str, export_id: str, request: Request, after_sequence: int = Query(default=0, ge=0, le=2_147_483_647), limit: int = Query(default=100, ge=1, le=200)):
    owner, repo = await _repository(request)
    if len(export_id) != 32 or any(c not in "0123456789abcdef" for c in export_id):
        raise HTTPException(422, "Invalid export identifier")
    events = await repo.audit(owner, project_id, export_id, after_sequence=after_sequence, limit=limit)
    return {"events": events, "next_after_sequence": events[-1]["sequence"] if len(events) == limit else None}
