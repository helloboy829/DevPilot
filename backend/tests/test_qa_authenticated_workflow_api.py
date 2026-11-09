"""Offline multi-account QA through real local login, JWT, CSRF and RBAC.

Only synthetic users/keys/data in migrated temporary SQLite. Reuse the real
Worker fixture's fail-closed DNS/wire substitution, NOT its synthetic identity
middleware. No production lifespan, configuration, target, model or deployment.
"""

import asyncio
import io
import socket
from contextlib import AsyncExitStack
from datetime import timedelta
from http.cookies import SimpleCookie
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pdfminer.high_level import extract_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_qa_workflow_api import CANARIES, GOLD, INPUTS, NOTE, OUTPUTS, collect, create_plan, response_json, review
from test_qa_workflow_api import workflow as workflow

from app.evaluation.repository import EvaluationRepository
from app.evaluation.schema import upgrade_evaluation_schema
from app.gateway import authz, deps, internal_auth
from app.gateway.auth import config as auth_config
from app.gateway.auth.config import AuthConfig
from app.gateway.auth.jwt import create_access_token
from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.repositories.sqlite import SQLiteUserRepository
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.authz import Permissions
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import auth, evaluation_projects, evaluation_review_tasks
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.persistence.component_tests.model import ComponentRow
from deerflow.persistence.user.model import UserRow

ORIGIN = "https://fixture.example.test"
PASSWORD = "Synthetic-only-Password42!"
TASK_ROOT = "/api/evaluation/review-tasks/"
PERMISSIONS = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_WRITE, Permissions.EVALUATION_PROJECTS_REVIEW]
ACTORS = ("owner", "reviewer_a", "reviewer_b", "arbitrator", "outsider")


def route_policy(*, deny=()):
    return AuthorizationConfig(
        enabled=True,
        fail_closed=True,
        provider=AuthorizationProviderConfig(
            use="deerflow.authz.rbac:RbacAuthorizationProvider",
            config={"roles": {"user": {"routes": {"allow": PERMISSIONS, "deny": list(deny)}}}},
        ),
    )


async def login(client, user, password=PASSWORD):
    response = await client.post("/api/v1/auth/login/local", data={"username": user.email, "password": password})
    assert response.status_code == 200, response.text
    assert "access_token" not in response.json()
    cookies = SimpleCookie()
    for value in response.headers.get_list("set-cookie"):
        cookies.load(value)
    access, csrf = cookies["access_token"], cookies["csrf_token"]
    # Preserve the existing OAuth-compatible Lax session cookie contract.
    assert access["httponly"] and access["secure"] and access["samesite"] == "lax"
    assert not csrf["httponly"] and csrf["secure"] and csrf["samesite"] == "strict"
    assert access["path"] == csrf["path"] == "/"
    assert int(access["max-age"]) == int(csrf["max-age"]) == 604800
    client.headers["X-CSRF-Token"] = client.cookies["csrf_token"]
    identity = await client.get("/api/v1/auth/me")
    assert identity.status_code == 200 and identity.json()["id"] == str(user.id)


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    """Override only workflow's API fixture; never stamp request.state identities."""
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("GATEWAY_CORS_ORIGINS", "")
    monkeypatch.setattr(auth_config, "_auth_config", AuthConfig(jwt_secret="synthetic-test-only-jwt-key-not-for-runtime"))
    monkeypatch.setattr(internal_auth, "_INTERNAL_AUTH_TOKEN", "synthetic-test-only-internal-token")
    monkeypatch.setattr(auth, "_login_attempts", {})
    for name, value in (("_route_provider_cache", {}), ("_route_provider_config_id", None), ("_route_provider_config_sig", None)):
        monkeypatch.setattr(authz, name, value)
    policy = {"value": route_policy()}
    monkeypatch.setattr(authz, "_get_route_authorization_config", lambda: policy["value"])

    def forbidden_network(*args, **kwargs):
        raise AssertionError("Real network forbidden in authenticated synthetic QA")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)
    for method in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, method, forbidden_network)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", forbidden_network)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'authenticated-qa.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: UserRow.__table__.create(c))
            await conn.run_sync(lambda c: ComponentRow.__table__.create(c))
        await upgrade_evaluation_schema(engine)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        repository = SQLiteUserRepository(sf)
        provider = LocalAuthProvider(repository)
        monkeypatch.setattr(deps, "_cached_repo", repository)
        monkeypatch.setattr(deps, "_cached_local_provider", provider)
        users = {actor: await provider.create_user(f"synthetic-{actor}@example.com", PASSWORD) for actor in ACTORS}
        assert len({user.id for user in users.values()}) == 5
        assert all(user.password_hash and user.password_hash != PASSWORD and user.system_role == "user" for user in users.values())
        async with sf.begin() as session:
            session.add(ComponentRow(id="c1", user_id=str(users["owner"].id), name="Synthetic component", transport="http_post", api_url="https://example.test/qa", response_mode="blocking", validation_type="manual_review"))
        app = FastAPI()
        app.state.evaluation_repo = EvaluationRepository(sf)
        app.include_router(auth.router)
        app.include_router(evaluation_projects.router)
        app.include_router(evaluation_review_tasks.router)
        app.include_router(evaluation_review_tasks.project_router)
        # Same order as Gateway: CSRF is outermost, auth resolves DB-backed user.
        app.add_middleware(AuthMiddleware)
        app.add_middleware(CSRFMiddleware)
        async with AsyncExitStack() as stack:
            clients = {}
            for actor, user in users.items():
                client = await stack.enter_async_context(httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN, headers={"Origin": ORIGIN}))
                await login(client, user)
                clients[actor] = client
            app.state.test_accounts = SimpleNamespace(users=users, clients=clients, provider=provider, policy=policy)
            owner = clients["owner"]
            project = response_json(await owner.post("/api/evaluation/projects", json={"name": "Synthetic authenticated project"}))
            yield owner, app, "/api/evaluation/projects/" + project["id"], None
    finally:
        await engine.dispose()


def accounts(state):
    return state.app.state.test_accounts


def command(task):
    return {"expected_revision": task["revision"], "confirmed": True}


async def task_payload(state, root, ordinal):
    case = response_json(await state.client.get(root + f"/cases/{ordinal}"), sensitive=True)
    users = accounts(state).users
    return {
        "run_id": root.rsplit("/", 1)[1],
        "ordinal": ordinal,
        "case_hash": case["case_hash"],
        "reviewer_ids": [str(users[actor].id) for actor in ("reviewer_a", "reviewer_b")],
        "arbitrator_id": str(users["arbitrator"].id),
        "share_reference": True,
        "confirmed": True,
    }


async def create_task(state, root, ordinal):
    payload = await task_payload(state, root, ordinal)
    task_id = uuid4().hex
    path = state.base + "/review-tasks/" + task_id
    task = response_json(await state.client.post(path, json=payload))
    # Idempotent existing receipt is checked, never used to retry an unknown write.
    assert response_json(await state.client.get(TASK_ROOT + task_id)) == task
    return TASK_ROOT + task_id, task, payload


async def vote(state, path, actor, decision):
    client = accounts(state).clients[actor]
    task = response_json(await client.get(path))
    claim = response_json(await client.post(path + "/claim", json=command(task)))
    payload = {**command(claim), "subject_hash": claim["subject_hash"], "decision": decision, "note": NOTE}
    # A real login and a lease do not replace the explicit evidence-open receipt.
    response_json(await client.post(path + "/decisions", json=payload), 409)
    case = response_json(await client.get(path + "/case"), sensitive=True)
    ordinal = case["ordinal"]
    assert (case["input"], case["expected"], case["output"]) == (INPUTS[ordinal - 1], GOLD[ordinal - 1], OUTPUTS[ordinal - 1])
    assert len(case["prior_decisions"]) == (2 if actor == "arbitrator" else 0)
    return response_json(await client.post(path + "/decisions", json=payload))


def source(assessment):
    return {
        "run_id": assessment["run_id"],
        "summary_hash": assessment["assessment"]["summary_hash"],
        "assessment_id": assessment["id"],
        "assessment_revision": assessment["revision"],
        "assessment_hash": assessment["assessment_hash"],
    }


@pytest.mark.asyncio
async def test_real_login_cookie_csrf_and_parallel_owner_isolation(api):
    owner, app, base, _ = api
    identities = app.state.test_accounts
    outsider = identities.clients["outsider"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as anonymous:
        assert (await anonymous.get(base + "/datasets")).status_code == 401
        denied = await anonymous.post("/api/v1/auth/login/local", data={"username": identities.users["owner"].email, "password": PASSWORD}, headers={"Origin": "https://hostile.example.test"})
        assert denied.status_code == 403 and "access_token" not in anonymous.cookies
        denied = await anonymous.post("/api/v1/auth/login/local", data={"username": identities.users["owner"].email, "password": "wrong-synthetic-password"})
        assert denied.status_code == 401 and "access_token" not in anonymous.cookies
    projects = response_json(await owner.get("/api/evaluation/projects"))
    for header in ("", "mismatched-token"):
        assert (await owner.post("/api/evaluation/projects", json={"name": "Must not be created"}, headers={"X-CSRF-Token": header})).status_code == 403
    # Matching header alone is not enough: remove only the cookie on a new client.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN, cookies={"access_token": owner.cookies["access_token"]}) as no_csrf:
        assert (await no_csrf.post("/api/evaluation/projects", json={"name": "Must not be created"}, headers={"X-CSRF-Token": owner.cookies["csrf_token"]})).status_code == 403
    assert response_json(await owner.get("/api/evaluation/projects")) == projects
    for _ in range(3):
        permitted, denied = await asyncio.gather(owner.get(base + "/datasets"), outsider.get(base + "/datasets"))
        response_json(permitted)
        response_json(denied, 404)
    assert response_json(await outsider.get("/api/evaluation/projects"))["projects"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "junk", "expired", "wrong_signature", "unknown_user", "stale_version"])
async def test_real_session_rejects_invalid_or_unresolvable_identity(api, kind):
    owner, app, base, _ = api
    user = app.state.test_accounts.users["owner"]
    token = {
        "missing": None,
        "junk": "not-a-jwt",
        "expired": create_access_token(str(user.id), expires_delta=timedelta(seconds=-10)),
        "wrong_signature": create_access_token(str(user.id)),
        "unknown_user": create_access_token(str(uuid4())),
        "stale_version": create_access_token(str(user.id), token_version=1),
    }[kind]
    if kind == "wrong_signature":
        # Change signature bytes, not just non-significant base64 padding bits.
        head, body, signature = token.split(".")
        token = ".".join((head, body, ("A" if signature[0] != "A" else "B") + signature[1:]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN, cookies={} if token is None else {"access_token": token}) as client:
        response = await client.get(base + "/datasets")
        assert response.status_code == 401
        assert all(value not in response.text for value in [*CANARIES, PASSWORD, str(user.id)])
    response_json(await owner.get(base + "/datasets"))


@pytest.mark.asyncio
async def test_password_change_revokes_old_cookie_but_keeps_new_session_and_other_accounts(api):
    owner, app, base, _ = api
    identities = app.state.test_accounts
    old_token = owner.cookies["access_token"]
    changed = await owner.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": "New-synthetic-Password42!"})
    assert changed.status_code == 200, changed.text
    owner.headers["X-CSRF-Token"] = owner.cookies["csrf_token"]
    assert owner.cookies["access_token"] != old_token
    persisted = await identities.provider.get_user(str(identities.users["owner"].id))
    assert persisted.token_version == 1
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN, cookies={"access_token": old_token}) as stale:
        assert (await stale.get(base + "/datasets")).status_code == 401
    response_json(await owner.get(base + "/datasets"))
    for actor in ACTORS[1:]:
        response = await identities.clients[actor].get("/api/v1/auth/me")
        assert response.status_code == 200 and response.json()["id"] == str(identities.users[actor].id)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "needs_setup", "owner", "duplicate", "reference_not_shared"])
async def test_real_account_lookup_and_explicit_independent_sharing_are_required(workflow, mode):
    state = workflow
    root, _ = await collect(state, await create_plan(state, "v1"), build="v1")
    payload = await task_payload(state, root, 1)
    identities = accounts(state)
    if mode == "missing":
        payload["arbitrator_id"] = str(uuid4())
    elif mode == "needs_setup":
        user = await identities.provider.get_user(payload["arbitrator_id"])
        user.needs_setup = True
        await identities.provider.update_user(user)
    elif mode == "owner":
        payload["reviewer_ids"][0] = str(identities.users["owner"].id)
    elif mode == "duplicate":
        payload["arbitrator_id"] = payload["reviewer_ids"][0]
    else:
        payload["share_reference"] = False
    task_id = uuid4().hex
    response_json(await state.client.post(state.base + "/review-tasks/" + task_id, json=payload), 422 if mode in {"duplicate", "reference_not_shared"} else 409)
    response_json(await state.client.get(TASK_ROOT + task_id), 404)
    assert response_json(await state.client.get(state.base + "/review-tasks"))["tasks"] == []
    assert len(state.sent) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", PERMISSIONS)
async def test_real_rbac_deny_wins_and_denied_commands_do_not_advance_task(workflow, permission):
    state = workflow
    plan = await create_plan(state, "v1")
    root, _ = await collect(state, plan, build="v1")
    path, original, _ = await create_task(state, root, 1)
    identities = accounts(state)
    identities.policy["value"] = route_policy(deny=[permission])
    if permission == Permissions.EVALUATION_PROJECTS_READ:
        assert (await state.client.get(path)).status_code == 403
    elif permission == Permissions.EVALUATION_PROJECTS_WRITE:
        assert (await state.client.post(path + "/cancel", json=command(original))).status_code == 403
    else:
        reviewer = identities.clients["reviewer_a"]
        task = response_json(await reviewer.get(path))
        assert (await reviewer.post(path + "/claim", json=command(task))).status_code == 403
        assert (await reviewer.get(path + "/case")).status_code == 403
    identities.policy["value"] = route_policy()
    assert response_json(await state.client.get(path)) == original
    assert len(state.sent) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_authenticated_worker_blind_review_historical_archives_and_exports(workflow, caplog, concurrency):
    state, records, reports, task_paths = workflow, [], [], []
    identities = accounts(state)
    plans = {build: await create_plan(state, build, concurrency=concurrency) for build in ("v1", "v2")}
    for build, outcomes in (("v1", ("pass", "fail", "pass")), ("v2", ("pass", "pass", "pass"))):
        state.clock["ms"] += 1000
        root, execution = await collect(state, plans[build], build=build)
        assert execution["state"] == "collected"
        if build == "v1":
            for ordinal in range(1, 4):
                _, _, result = await review(state, root, ordinal, "pass")
                response_json(result)
        initial = response_json(await state.client.get(root + "/independent-assessment"))
        assert initial["counts"] == {"pass": 0, "fail": 0, "uncertain": 0, "unreviewed": 3}
        for ordinal, outcome in enumerate(outcomes, 1):
            path, created, payload = await create_task(state, root, ordinal)
            task_paths.append(path)
            if build == "v1" and ordinal == 1:
                response_json(await state.client.post(path + "/claim", json=command(created)), 409)
                response_json(await state.client.get(path + "/case"), 409)
                arb = identities.clients["arbitrator"]
                response_json(await arb.post(path + "/claim", json=command(created)), 409)
                reviewer = identities.clients["reviewer_a"]
                response_json(await reviewer.get(path + "/case"), 409)
                response_json(await reviewer.post(path + "/cancel", json=command(created)), 404)
                response_json(await reviewer.post(state.base + "/review-tasks/" + uuid4().hex, json=payload), 404)
                assert response_json(await state.client.get(path)) == created
            for actor in ("reviewer_a", "reviewer_b", "arbitrator"):
                client = identities.clients[actor]
                for target in (state.base + "/datasets", state.base + "/review-tasks", root + f"/cases/{ordinal}", path + "/result"):
                    response_json(await client.get(target), 404)
            outsider = identities.clients["outsider"]
            response_json(await outsider.get(path), 404)
            assert response_json(await outsider.get(TASK_ROOT.rstrip("/")))["tasks"] == []
            # A first-round disagreement MUST reach a separately logged-in third user.
            first = await vote(state, path, "reviewer_a", "pass")
            assert first["status"] == "in_review"
            inbox = await identities.clients["reviewer_b"].get(TASK_ROOT.rstrip("/"))
            response_json(inbox)
            assert str(identities.users["reviewer_a"].id) not in inbox.text and str(identities.users["arbitrator"].id) not in inbox.text
            second = await vote(state, path, "reviewer_b", outcome)
            if outcome == "fail":
                assert second["status"] == "escalated"
                final = await vote(state, path, "arbitrator", outcome)
            else:
                final = second
            assert final["status"] == "resolved"
            result = response_json(await state.client.get(path + "/result"), sensitive=True)
            assert result["resolution"]["outcome"] == outcome and result["resolution"]["approval"] == "not_approved"
            assert {decision["note"] for decision in result["decisions"]} == {NOTE}
        preview = response_json(await state.client.get(root + "/independent-assessment"))
        assert preview["counts"] == {"pass": outcomes.count("pass"), "fail": outcomes.count("fail"), "uncertain": 0, "unreviewed": 0}
        assert preview["human_pass_rate"]["denominator"] == 3
        assert preview["criteria_evaluation"]["status"] == ("not_met" if build == "v1" else "met")
        assert preview["acceptance"] == "not_approved"
        assessment_path = root + "/assessments/" + uuid4().hex
        assessment = response_json(await state.client.post(assessment_path, json={"summary_hash": preview["summary_hash"], "expected_previous_revision": 0, "confirmed": True}))
        records.append((assessment_path, assessment))
        report_path = state.base + "/independent-report-archives/" + uuid4().hex
        report = response_json(
            await state.client.put(report_path, json={"title": "Synthetic authenticated historical report", "template_id": "independent-qa-project-en", "template_version": "1.0.0", "sources": [source(assessment)], "confirmed": True})
        )
        assert report["acceptance"] == "not_approved"
        reports.append((report_path, report))
    comparison_path = state.base + "/independent-retest-archives/" + uuid4().hex
    comparison = response_json(await state.client.put(comparison_path, json={"baseline": source(records[0][1]), "retest": source(records[1][1]), "confirmed": True}))
    assert comparison["transitions"] == {"fail_to_pass": 1, "pass_to_fail": 0, "pass_to_pass": 2, "fail_to_fail": 0}
    assert comparison["pass_rate_delta"]["denominator"] == 3 and len(comparison["cases"]) == 3
    assert comparison["acceptance"] == "not_approved"
    for path, document, prefix in [(path, doc, "independent-qa") for path, doc in reports] + [(comparison_path, comparison, "independent-retest")]:
        response_json(await state.client.get(path))
        for extension, magic in (("docx", b"PK"), ("pdf", b"%PDF-")):
            renderer = f"{prefix}-{extension}-v1"
            url = path + "/exports/" + renderer + "?archive_hash=" + document["archive_hash"]
            exported = await state.client.get(url)
            assert exported.status_code == 200 and exported.content.startswith(magic)
            assert exported.headers["x-devpilot-renderer"] == renderer and "no-store" in exported.headers["cache-control"]
            if extension == "pdf":
                text = extract_text(io.BytesIO(exported.content))
                assert "NOT APPROVED" in text and all(value not in text for value in CANARIES)
            for actor in ACTORS[1:]:
                response_json(await identities.clients[actor].get(url), 404)
    # Reopening tasks cannot rewrite historical assessment or archive receipts.
    original = response_json(await state.client.get(task_paths[0] + "/result"), sensitive=True)
    task = response_json(await state.client.get(task_paths[0]))
    reopened = response_json(await state.client.post(task_paths[0] + "/reopen", json={**command(task), "reason": NOTE}))
    assert reopened["round"] == 2
    assert response_json(await state.client.get(task_paths[0] + "/result?round_number=1"), sensitive=True) == original
    for path, document in records + reports + [(comparison_path, comparison)]:
        assert response_json(await state.client.get(path)) == document
        for actor in ACTORS[1:]:
            response_json(await identities.clients[actor].get(path), 404)
    assert len(state.sent) == len(set(state.sent)) == 6
    assert all(value not in caplog.text for value in [*CANARIES, PASSWORD])
