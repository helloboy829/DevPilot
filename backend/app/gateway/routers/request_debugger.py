"""Authenticated, non-persistent interface debugging. Request bodies are never logged."""

import asyncio
from typing import Any

from devpilot.http import RequestSpec, parse_curl
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.http import send_request
from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from app.gateway.private_route import PrivateValidationRoute

router = APIRouter(route_class=PrivateValidationRoute, prefix="/api/component-tests/debug", tags=["component-tests"])
_slots = asyncio.Semaphore(4)


class CurlImport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command: str = Field(min_length=1, max_length=300000)


class SendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    spec: dict[str, Any]
    consent: bool


@router.post("/parse")
@require_permission("threads", "write")
async def import_curl(payload: CurlImport, request: Request):
    try:
        return JSONResponse({"spec": parse_curl(payload.command).to_dict()}, headers={"Cache-Control": "private, no-store"})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/send")
@require_permission("threads", "write")
@require_permission("runs", "create")
async def debug_send(payload: SendRequest, request: Request, config=Depends(get_config)):
    if payload.consent is not True:
        raise HTTPException(422, "Explicit permission to send this request is required")
    if _slots.locked():
        raise HTTPException(429, "Too many debug requests")
    async with _slots:
        try:
            spec = RequestSpec.from_dict(payload.spec)
            result = await send_request(spec, config)
            return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception:
            raise HTTPException(502, "Request failed or timed out; provider details are not logged") from None
