"""Administrator-only catalog mutations. Never return or log model credentials."""

import asyncio
import json
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.gateway.deps import get_optional_user_from_request, require_admin_user
from app.gateway.private_route import PrivateValidationRoute
from deerflow.config.managed_models import ManagedModel, catalog_from_env

router = APIRouter(route_class=PrivateValidationRoute, prefix="/api/model-management", tags=["models"])
_provider_request_slots = asyncio.Semaphore(1)
_MAX_MODEL_LIST_BYTES = 512 * 1024
_MAX_MODEL_OPTIONS = 100
_MODEL_LIST_ERROR = "Could not retrieve model IDs. Check the endpoint and credentials, or enter a model ID manually."


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


class DiscoverModels(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provider: Literal["openai_compatible", "openai_responses", "anthropic", "gemini"]
    base_url: str = Field(min_length=1, max_length=2048)
    profile_name: str | None = Field(default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    api_key: str | None = Field(default=None, min_length=1, max_length=4096, repr=False)
    clear_credential: bool = False
    consent: Literal[True]

    @model_validator(mode="after")
    def validate_connection(self):
        if self.clear_credential and self.api_key is not None:
            raise ValueError("Supply a new credential OR clear the credential, not both")
        validated = ManagedModel(name="discovery", model="discovery", base_url=self.base_url)
        self.base_url = validated.base_url
        return self


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


async def _discovery_credential(catalog, payload: DiscoverModels) -> str | None:
    if payload.api_key is not None or payload.clear_credential or payload.profile_name is None:
        return payload.api_key

    state = await asyncio.to_thread(catalog.state)
    saved = next((row for row in state["models"] if row["name"] == payload.profile_name), None)
    if saved is None or not saved.get("api_key"):
        return None
    if saved["provider"] != payload.provider or saved["base_url"] != payload.base_url:
        raise HTTPException(409, "Re-enter the API key before listing models after changing the endpoint or protocol")
    return saved["api_key"]


def _model_list_url(provider: str, base_url: str) -> str:
    path = {
        "openai_compatible": "/models",
        "openai_responses": "/models",
        "anthropic": "/v1/models",
        "gemini": "/v1beta/models",
    }[provider]
    return f"{base_url.rstrip('/')}{path}"


def _model_list_headers(provider: str, api_key: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        if provider in {"openai_compatible", "openai_responses"}:
            headers["Authorization"] = f"Bearer {api_key}"
        elif provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["x-goog-api-key"] = api_key
    return headers


async def _request_model_list(provider: str, base_url: str, api_key: str | None) -> dict:
    url = _model_list_url(provider, base_url)
    headers = _model_list_headers(provider, api_key)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0, connect=3.0),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code != 200:
                raise ValueError("Provider did not return a model list")
            content_length = response.headers.get("content-length")
            if content_length is not None and int(content_length) > _MAX_MODEL_LIST_BYTES:
                raise ValueError("Provider response exceeded the size limit")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > _MAX_MODEL_LIST_BYTES:
                    raise ValueError("Provider response exceeded the size limit")
    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise ValueError("Provider returned an invalid model list")
    return decoded


def _public_model_options(provider: str, response: dict) -> dict:
    rows = response.get("models") if provider == "gemini" else response.get("data")
    if not isinstance(rows, list):
        raise ValueError("Provider returned an invalid model list")

    options = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get("id") if provider != "gemini" else row.get("name")
        if not isinstance(identifier, str):
            continue
        identifier = identifier.strip()
        if provider == "gemini" and identifier.startswith("models/"):
            identifier = identifier.removeprefix("models/")
        if not identifier or len(identifier) > 200 or any(ord(char) < 32 for char in identifier) or identifier in seen:
            continue
        raw_display_name = row.get("display_name") or row.get("displayName")
        if not raw_display_name and provider != "gemini":
            raw_display_name = row.get("name")
        display_name = raw_display_name.strip() if isinstance(raw_display_name, str) else identifier
        if not display_name or len(display_name) > 200 or any(ord(char) < 32 for char in display_name):
            display_name = identifier
        seen.add(identifier)
        options.append({"id": identifier, "display_name": display_name})

    truncated = len(options) > _MAX_MODEL_OPTIONS or bool(response.get("has_more") or response.get("nextPageToken"))
    return {"models": options[:_MAX_MODEL_OPTIONS], "truncated": truncated}


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


@router.post("/models/discover")
async def discover_models(payload: DiscoverModels, request: Request):
    catalog, _ = await _catalog(request)
    api_key = await _discovery_credential(catalog, payload)
    if _provider_request_slots.locked():
        raise HTTPException(429, "A model provider request is already active")
    async with _provider_request_slots:
        try:
            async with asyncio.timeout(10):
                response = await _request_model_list(payload.provider, payload.base_url, api_key)
            return _response(_public_model_options(payload.provider, response))
        except Exception:
            raise HTTPException(502, _MODEL_LIST_ERROR) from None


@router.post("/models/{name}/probe")
async def probe_model(name: str, payload: Probe, request: Request):
    catalog, _ = await _catalog(request)
    public = await asyncio.to_thread(catalog.public)
    if not any(row["name"] == name and row["enabled"] for row in public["models"]):
        raise HTTPException(404, "Enabled managed model not found")
    if _provider_request_slots.locked():
        raise HTTPException(429, "A model probe is already active")
    async with _provider_request_slots:
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
