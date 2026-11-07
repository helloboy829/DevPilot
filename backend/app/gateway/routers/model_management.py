"""Administrator-only catalog mutations. Never return or log model credentials."""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.gateway.deps import get_optional_user_from_request, require_admin_user
from app.gateway.private_route import PrivateValidationRoute
from deerflow.config.managed_models import ManagedModel, catalog_from_env

router = APIRouter(route_class=PrivateValidationRoute, prefix="/api/model-management", tags=["models"])
_probe_slots = asyncio.Semaphore(1)


class SaveModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: ManagedModel
    revision: int = Field(ge=0)


class AssignRoles(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    roles: dict[str, str | None] = Field(max_length=5)
    revision: int = Field(ge=0)


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    consent: Literal[True]


async def _catalog(request):
    await require_admin_user(request, detail="Only administrators may manage platform models")
    catalog = catalog_from_env()
    if catalog is None:
        raise HTTPException(503, "Operator must set DEVPILOT_MODEL_CATALOG_DIR to a persistent private directory")
    user = await get_optional_user_from_request(request)
    return catalog, str(user.id)


def _operator_config():
    import yaml

    from deerflow.config.app_config import AppConfig

    with AppConfig.resolve_config_path().open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


async def _check_operator_reference(name):
    config = await asyncio.to_thread(_operator_config)
    if config.get("reports_agent", {}).get("model_name") == name:
        raise HTTPException(409, "Model is referenced by operator reports_agent configuration")


def _response(data):
    return JSONResponse(data, headers={"Cache-Control": "private, no-store"})


@router.get("")
async def list_catalog(request: Request):
    catalog, _ = await _catalog(request)
    return _response(await asyncio.to_thread(catalog.public))


@router.put("/models")
async def save_model(payload: SaveModel, request: Request):
    catalog, actor = await _catalog(request)
    # Operator YAML entries are immutable from this API.
    config = await asyncio.to_thread(_operator_config)
    if payload.model.name in {row["name"] for row in config.get("models", [])}:
        raise HTTPException(409, "Name belongs to an operator-managed model; use a new identifier")
    if not payload.model.enabled:
        await _check_operator_reference(payload.model.name)
    try:
        return _response(await asyncio.to_thread(catalog.save_model, payload.model, actor=actor, expected_revision=payload.revision))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.put("/roles")
async def assign_roles(payload: AssignRoles, request: Request):
    catalog, actor = await _catalog(request)
    try:
        return _response(await asyncio.to_thread(catalog.assign, payload.roles, actor=actor, expected_revision=payload.revision))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.delete("/models/{name}")
async def delete_model(name: str, revision: int, request: Request):
    catalog, actor = await _catalog(request)
    await _check_operator_reference(name)
    try:
        return _response(await asyncio.to_thread(catalog.delete, name, actor=actor, expected_revision=revision))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/models/{name}/probe")
async def probe_model(name: str, payload: Probe, request: Request):
    catalog, _ = await _catalog(request)
    public = await asyncio.to_thread(catalog.public)
    if not any(row["name"] == name and row["enabled"] for row in public["models"]):
        raise HTTPException(404, "Enabled managed model not found")
    if _probe_slots.locked():
        raise HTTPException(429, "A model probe is already active")
    async with _probe_slots:
        try:
            from langsmith import tracing_context

            from deerflow.config import get_app_config
            from deerflow.models import create_chat_model

            config = await asyncio.to_thread(get_app_config)
            with tracing_context(enabled=False):
                async with asyncio.timeout(20):
                    model = await asyncio.to_thread(create_chat_model, name=name, app_config=config, attach_tracing=False, model_overrides={"max_tokens": 16, "max_retries": 0, "callbacks": []})
                    await model.ainvoke("Reply with OK. Connectivity check only. No business data.", config={"callbacks": []})
            return _response({"ok": True, "model_name": name})
        except Exception:
            raise HTTPException(502, "Model connectivity check failed or timed out; no provider error body retained") from None
