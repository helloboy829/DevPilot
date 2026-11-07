"""Scheduled component evaluation: immutable plans, no model-selected targets or load."""

import asyncio
import hashlib
import json
import uuid
from types import SimpleNamespace

import httpx
from devpilot.http import RequestSpec
from fastapi import HTTPException

from app.evaluation.http import resolve_destination

ASSISTANT_ID = "devpilot_component_evaluation_v1"


def component_fingerprint(component):
    fields = ("id", "transport", "api_url", "response_mode", "supports_streaming", "validation_type", "acceptance_criteria")
    return hashlib.sha256(json.dumps({k: component.get(k) for k in fields}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_plan(test_type, params):
    if not isinstance(params, dict) or len(json.dumps(params)) > 262144:
        raise ValueError("Test plan exceeds 256 KiB")
    allowed = {"samples", "timeout_seconds"} if test_type == "effect" else {"payload", "max_requests", "concurrency_levels", "timeout_seconds", "model"}
    if test_type not in {"effect", "perf"} or set(params) - allowed:
        raise ValueError("Unsupported plan fields; headers, credentials and model judging are not permitted in scheduled plans")
    timeout = params.get("timeout_seconds", 30)
    if type(timeout) not in (int, float) or not 1 <= timeout <= 120:
        raise ValueError("Timeout must be between 1 and 120 seconds")
    if test_type == "effect":
        samples = params.get("samples")
        if not isinstance(samples, list) or not 1 <= len(samples) <= 1000 or any(not isinstance(s, dict) for s in samples):
            raise ValueError("Effect plan requires 1 to 1000 sample objects")
    else:
        count = params.get("max_requests", 100)
        levels = params.get("concurrency_levels", [1, 5])
        if type(count) is not int or not 1 <= count <= 1000 or not isinstance(levels, list) or not 1 <= len(levels) <= 5 or any(type(n) is not int or not 1 <= n <= 20 for n in levels):
            raise ValueError("Performance plan: 1..1000 requests per level, 1..5 levels, concurrency 1..20")
        if not isinstance(params.get("payload", {}), dict):
            raise ValueError("Performance payload must be an object")

    # Do not allow common credential-bearing fields anywhere in stored parameters.
    def reject_secrets(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"api_key", "api_token", "authorization", "password", "cookie", "access_token", "secret"}:
                    raise ValueError("Keep credentials in the registered component, not the schedule plan")
                reject_secrets(child)
        elif isinstance(value, list):
            for child in value:
                reject_secrets(child)

    reject_secrets(params)


def freeze_plan(component, test_type, params):
    validate_plan(test_type, params)
    if component.get("enabled") is False:
        raise ValueError("Component is disabled")
    params = json.loads(json.dumps(params, allow_nan=False))
    params.setdefault("timeout_seconds", 30)
    if test_type == "perf":
        params.setdefault("max_requests", 100)
        params.setdefault("concurrency_levels", [1, 5])
    return {"schema_version": "evaluation-plan.v1", "component_id": component["id"], "component_sha256": component_fingerprint(component), "test_type": test_type, "params": params}


class PinnedEvaluationTransport(httpx.AsyncBaseTransport):
    def __init__(self, config, url):
        self.config, self.url = config, httpx.URL(url)
        self.inner = httpx.AsyncHTTPTransport(verify=True, trust_env=False, retries=0)

    async def handle_async_request(self, request):
        if (request.url.scheme, request.url.host, request.url.port) != (self.url.scheme, self.url.host, self.url.port):
            raise ValueError("Scheduled request changed destination")
        ip = await resolve_destination(RequestSpec(url=str(request.url)), self.config)
        request.headers["host"] = request.url.netloc.decode("ascii")
        request.extensions["sni_hostname"] = request.url.host
        request.url = request.url.copy_with(host=ip)
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


async def launch_scheduled_dispatch(*, app, assistant_id, **kwargs):
    if assistant_id != ASSISTANT_ID:
        from app.gateway.services import launch_scheduled_thread_run

        return await launch_scheduled_thread_run(app=app, assistant_id=assistant_id, **kwargs)
    from deerflow.config import get_app_config

    user_id = kwargs.get("owner_user_id")
    try:
        from app.gateway.authz import Permissions, resolve_route_permissions
        from app.gateway.deps import get_local_provider

        user = await get_local_provider().get_user(user_id) if user_id else None
        if user is None or user.needs_setup:
            raise ValueError("Schedule owner unavailable")
        permissions = await resolve_route_permissions(user, is_internal=False)
        if not {Permissions.THREADS_WRITE, Permissions.RUNS_CREATE}.issubset(permissions):
            raise ValueError("Schedule owner no longer has execution permission")
        plan = json.loads(kwargs["prompt"])
        if plan.get("schema_version") != "evaluation-plan.v1":
            raise ValueError("Invalid evaluation plan version")
        component = await app.state.component_repo.get(plan["component_id"], user_id=user_id)
        if component is None or component.get("enabled") is False or component_fingerprint(component) != plan["component_sha256"]:
            raise ValueError("Component changed or is unavailable; confirm a new schedule")
        validate_plan(plan["test_type"], plan["params"])
        config = await asyncio.to_thread(get_app_config)
        await resolve_destination(RequestSpec(url=component["api_url"]), config)
    except Exception:
        raise HTTPException(409, "Scheduled evaluation plan is invalid, changed, or blocked by outbound policy") from None
    run_id = "run-" + uuid.uuid4().hex
    await app.state.component_test_run_repo.create(run_id=run_id, user_id=user_id, component_id=component["id"], test_type=plan["test_type"], params=plan["params"])
    client = httpx.AsyncClient(transport=PinnedEvaluationTransport(config, component["api_url"]), trust_env=False, follow_redirects=False, timeout=float(plan["params"].get("timeout_seconds", 30)))
    metadata = kwargs.get("metadata") or {}

    async def completed(status):
        record = SimpleNamespace(
            metadata=metadata, user_id=user_id, status=SimpleNamespace(value="success" if status == "completed" else "error"), error=None if status == "completed" else "Evaluation execution failed or was interrupted", run_id=run_id
        )
        await app.state.scheduled_task_service.handle_run_completion(record)

    if plan["test_type"] == "effect":
        # Scheduled target calls do not imply consent to disclose outputs to a judge.
        component = {**component, "validation_type": "manual_review"}
    app.state.component_test_service.enqueue(run_id=run_id, user_id=user_id, component=component, test_type=plan["test_type"], params=plan["params"], http_client=client, on_complete=completed)
    return {"run_id": run_id, "thread_id": kwargs["thread_id"]}
