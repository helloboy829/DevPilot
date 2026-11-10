"""Human-only bounded external technical quarantine; no output/evidence intake."""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.authorized_exports import _drain
from app.evaluation.external_qa_metadata import ExternalMetadataRejected
from app.evaluation.external_qa_quarantine import MAX_HTTP_BYTES, ExternalQAIntakeCreate, IntakeIntegrityError
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.gateway.authz import require_permission
from app.gateway.private_route import PrivateValidationRoute
from app.gateway.routers.evaluation_projects import _context, _require_human

_PRIVATE = {"Cache-Control": "private, no-store"}


def _envelope(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        json.loads(data.decode("utf-8"), object_pairs_hook=unique)
        return True
    except (ValueError, UnicodeError, RecursionError):
        return False


class ExternalQAIntakeRoute(PrivateValidationRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            try:
                if request.method == "PUT":
                    chunks, size = [], 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_HTTP_BYTES:
                            raise HTTPException(413, "External metadata request is too large", headers=_PRIVATE)
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if not await _drain(asyncio.to_thread(_envelope, data)):
                        raise HTTPException(422, "Invalid external metadata request", headers=_PRIVATE)
                    request._body = data
                return await handler(request)
            except NotFound:
                raise HTTPException(404, "External metadata archive or source not found; reconcile only by GET of the same intake ID, never resend PUT", headers=_PRIVATE) from None
            except Conflict:
                raise HTTPException(409, "Archive exists or source changed; reconcile only by GET of the same intake ID, never resend PUT", headers=_PRIVATE) from None
            except ExternalMetadataRejected:
                raise HTTPException(422, "External QA metadata rejected; no evidence accepted", headers=_PRIVATE) from None
            except (IntakeIntegrityError, RequestProtectionError, SQLAlchemyError):
                raise HTTPException(503, "Archive unavailable or write outcome unknown; inspect only the same intake ID by GET, never automatically resend PUT", headers=_PRIVATE) from None

        return bounded


router = APIRouter(prefix="/api/evaluation/projects", tags=["evaluation-external-qa"], route_class=ExternalQAIntakeRoute)


async def _repository(request):
    owner, _ = await _context(request)
    _require_human(request)
    repo = getattr(request.app.state, "evaluation_external_qa_repo", None)
    if repo is None:
        raise HTTPException(503, "External metadata service unavailable")
    return owner, repo


def _id(value):
    if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise HTTPException(422, "Invalid intake identifier")
    return value


@router.put("/{project_id}/external-qa-intakes/{intake_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_projects", "write")
@require_permission("evaluation_projects", "review")
@require_permission("evaluation_exports", "read")
@require_permission("evaluation_external_qa", "create")
async def create_intake(project_id: str, intake_id: str, payload: ExternalQAIntakeCreate, request: Request):
    owner, repo = await _repository(request)
    return await repo.create(owner, project_id, _id(intake_id), payload)


@router.get("/{project_id}/external-qa-intakes/{intake_id}")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_external_qa", "read")
async def get_intake(project_id: str, intake_id: str, request: Request):
    owner, repo = await _repository(request)
    return await repo.get(owner, project_id, _id(intake_id))


@router.get("/{project_id}/external-qa-intakes/{intake_id}/audit")
@require_permission("evaluation_projects", "read")
@require_permission("evaluation_external_qa", "read")
async def intake_audit(project_id: str, intake_id: str, request: Request, after_sequence: int = Query(default=0, ge=0, le=2_147_483_647), limit: int = Query(default=100, ge=1, le=200)):
    owner, repo = await _repository(request)
    events = await repo.audit(owner, project_id, _id(intake_id), after_sequence=after_sequence, limit=limit)
    return {"events": events, "next_after_sequence": events[-1]["sequence"] if len(events) == limit else None}
