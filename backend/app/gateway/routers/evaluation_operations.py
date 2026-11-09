"""Human administrator aggregate reads only; no release/reclaim/execute route."""

import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.execution_diagnostics import reservation_snapshot
from app.gateway.authz import _is_internal_caller, require_permission
from app.gateway.deps import require_admin_user
from app.gateway.private_route import PrivateValidationRoute

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evaluation/operations", tags=["evaluation-operations"], route_class=PrivateValidationRoute)


@router.get("/reservations")
@require_permission("evaluation_operations", "read")
async def get_reservations(request: Request):
    await require_admin_user(request, detail="Only human administrators may inspect execution reservations")
    if _is_internal_caller(request, request.state.auth.user):
        raise HTTPException(403, "Internal callers cannot inspect execution operations")
    repository = getattr(request.app.state, "evaluation_execution_repo", None)
    if repository is None:
        raise HTTPException(503, "Evaluation execution diagnostics are unavailable")
    try:
        return await reservation_snapshot(repository)
    except (SQLAlchemyError, ValueError):
        # Do not expose statements/parameters, source hashes or configuration.
        logger.warning("Execution reservation diagnostics failed; details suppressed")
        raise HTTPException(503, "Evaluation execution diagnostics are unavailable") from None
