"""Private explicit historical assessment bindings, with no target/model I/O."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError
from test_evaluation_registry_router import api as api
from test_qa_assessments import payload as assessment_payload
from test_qa_evidence import observation
from test_qa_evidence_router import setup_evidence
from test_qa_independent_archives import source
from test_review_tasks import ARB, A, B, command, decision

from app.evaluation.dispatch_journal import JournalLimits, JournalWriteUnconfirmed
from app.evaluation.plans import PlanCreate
from app.evaluation.qa_assessments import AssessmentRepository
from app.evaluation.qa_evidence import EvidenceRepository
from app.evaluation.qa_independent_archives import IndependentReportRepository, IndependentRetestRepository
from app.evaluation.review_tasks import ReviewTaskRepository, TaskCreate
from app.gateway.authz import Permissions

ID = "c" * 32


async def setup_archive(api, monkeypatch, *, pair=False):
    _, app, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    owner, project, run_id = str(UUID(int=1)), base.rsplit("/", 1)[1], root.rsplit("/", 1)[1]
    evidence = EvidenceRepository(app.state.evaluation_repo.sf)
    tasks = ReviewTaskRepository(evidence.sf)
    assessments = AssessmentRepository(evidence.sf)

    async def complete(run_id):
        case = await evidence.open_case(owner, project, run_id, 1)
        key = uuid4().hex
        await tasks.create_task(owner, project, key, TaskCreate(run_id=run_id, ordinal=1, case_hash=case["case_hash"], reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True))
        for actor in (A, B):
            claimed = await tasks.claim(actor, key, command(await tasks.get_task(actor, key)))
            await tasks.open_task(actor, key)
            await tasks.submit_decision(actor, key, decision(claimed))
        preview = await assessments.get_preview(owner, project, run_id)
        return await assessments.create_assessment(owner, project, run_id, uuid4().hex, assessment_payload(preview))

    first = await complete(run_id)
    report = {"title": "Synthetic independent draft", "template_id": "independent-qa-project-en", "template_version": "1.0.0", "sources": [source(first)], "confirmed": True}
    if not pair:
        return report
    run = await evidence.get_journal(owner, project, run_id)
    plan = await evidence.get_plan(owner, project, run["plan_id"])
    definition = {key: value for key, value in plan["definition"].items() if key in PlanCreate.model_fields}
    plan = await evidence.create_plan(owner, project, plan["component_id"], PlanCreate.model_validate({**definition, "version_label": "Synthetic v2", "confirmed": True}))
    second = await evidence.record_run(owner, project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=129))
    ticket = await evidence.record_dispatch(owner, project, second["id"], 1, body_bytes=20)
    await evidence.record_attempt(owner, project, second["id"], ticket, observation())
    second = await complete(second["id"])
    return {"baseline": source(first), "retest": source(second), "confirmed": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["report", "retest"])
async def test_explicit_api_archives_receipts_private_lists_and_legacy_isolation(api, monkeypatch, kind):
    client, _, base, _ = api
    payload = await setup_archive(api, monkeypatch, pair=kind == "retest")
    root = base + "/independent-" + kind + "-archives"
    path = root + "/" + ID
    created = await client.put(path, json=payload)
    assert created.status_code == 200, created.text
    doc = created.json()
    assert doc["acceptance"] == "not_approved"
    assert doc["schema"] == ("qa-independent-project-report-archive.v1" if kind == "report" else "qa-independent-retest-archive.v1")
    assert (await client.get(path)).json() == doc
    assert (await client.put(path, json=payload)).json() == doc
    listing = await client.get(root)
    key = "archives" if kind == "report" else "comparisons"
    assert len(listing.json()[key]) == 1
    assert not any(value in listing.text for value in ("document", "cases", "markdown", "request_hash"))
    assert (await client.get(base + "/" + kind + "-archives")).json()[key] == []
    for response in (created, listing, await client.get(path)):
        assert "no-store" in response.headers["cache-control"]
        assert not any(secret in response.text for secret in ("SYNTHETIC_OUTPUT", "SYNTHETIC_GOLD", "SYNTHETIC_INDEPENDENT_NOTE", A, B, "encrypted_payload"))
    assert (await client.delete(path)).status_code == 405
    assert (await client.patch(path, json=payload)).status_code == 405
    assert (await client.post(path + "/execute", json={})).status_code == 404
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    assert (await client.get(path)).json() == doc
    assert (await client.put(path, json=payload)).json() == doc


@pytest.mark.asyncio
async def test_all_seven_routes_enforce_owner_human_and_separate_permissions(api, monkeypatch):
    client, app, base, _ = api
    payload = await setup_archive(api, monkeypatch)
    report = base + "/independent-report-archives"
    retest = base + "/independent-retest-archives"
    assert (await client.put(report + "/" + ID, json=payload)).status_code == 200
    reads = [base + "/independent-report-templates", report, report + "/" + ID, retest, retest + "/" + ID]
    retest_payload = {"baseline": payload["sources"][0], "retest": {**payload["sources"][0], "run_id": "d" * 32}, "confirmed": True}
    writes = [(report + "/" + ID, payload), (retest + "/" + ID, retest_payload)]
    permissions = app.state.permissions
    for allowed in ([Permissions.EVALUATION_PROJECTS_READ], [Permissions.EVALUATION_PROJECTS_REVIEW], [Permissions.EVALUATION_PROJECTS_WRITE]):
        app.state.permissions = allowed
        assert [(await client.get(p)).status_code for p in reads] == [403] * 5
        assert [(await client.put(p, json=body)).status_code for p, body in writes] == [403, 403]
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW]
    assert [(await client.get(p)).status_code for p in reads] == [200, 200, 200, 200, 404]
    assert [(await client.put(p, json=body)).status_code for p, body in writes] == [403, 403]
    app.state.permissions = permissions
    app.state.internal = True
    assert [(await client.get(p)).status_code for p in reads] == [403] * 5
    assert [(await client.put(p, json=body)).status_code for p, body in writes] == [403, 403]
    app.state.internal = False
    for actor, status in ((2, 404), (0, 401)):
        app.state.actor = actor
        assert [(await client.get(p)).status_code for p in reads] == [status] * 5
        assert [(await client.put(p, json=body)).status_code for p, body in writes] == [status] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["report", "retest"])
@pytest.mark.parametrize("committed", [False, True])
async def test_unknown_writes_only_reconcile_same_id_and_errors_are_generic(api, monkeypatch, kind, committed):
    client, _, base, _ = api
    payload = await setup_archive(api, monkeypatch, pair=kind == "retest")
    cls, method = (IndependentReportRepository, "create_archive") if kind == "report" else (IndependentRetestRepository, "create_retest")
    original = getattr(cls, method)
    calls = 0

    async def uncertain(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if committed:
            await original(self, *args, **kwargs)
        raise JournalWriteUnconfirmed("SYNTHETIC_SECRET")

    monkeypatch.setattr(cls, method, uncertain)
    root = base + "/independent-" + kind + "-archives"
    path = root + "/" + ID
    response = await client.put(path, json=payload)
    assert response.status_code == 503 and "SYNTHETIC" not in response.text and "no-store" in response.headers["cache-control"]
    found = await client.get(path)
    assert found.status_code == (200 if committed else 404) and calls == 1
    key = "archives" if kind == "report" else "comparisons"
    assert len((await client.get(root)).json()[key]) == int(committed)

    async def failed(*args, **kwargs):
        raise OperationalError("SYNTHETIC_SQL", {"secret": "SYNTHETIC_SECRET"}, Exception("SYNTHETIC_FAILURE"))

    monkeypatch.setattr(cls, "list_archives" if kind == "report" else "list_retests", failed)
    response = await client.get(root)
    assert response.status_code == 503 and "SYNTHETIC" not in response.text and "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"confirmed": False}, {"metrics": {"pass": 999}}, {"sources": []}, {"template_id": "verified-qa-project-en"}])
async def test_strict_confirmation_legacy_template_rejection_and_redaction(api, monkeypatch, changes):
    client, _, base, _ = api
    payload = await setup_archive(api, monkeypatch)
    response = await client.put(base + "/independent-report-archives/" + ID, json={**payload, **changes})
    assert response.status_code == (409 if "template_id" in changes else 422)
    assert "SYNTHETIC" not in response.text and "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_pinned_independent_templates_are_not_legacy_aliases_and_requests_bounded(api):
    client, _, base, _ = api
    response = await client.get(base + "/independent-report-templates")
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    templates = response.json()["templates"]
    assert {(item["id"], item["version"]) for item in templates} == {("independent-qa-project-en", "1.0.0"), ("independent-qa-project-zh", "1.0.0")}
    for kind in ("report", "retest"):
        root = base + "/independent-" + kind + "-archives/"
        response = await client.get(root + "SYNTHETIC_SECRET")
        assert response.status_code == 422 and "SYNTHETIC_SECRET" not in response.text
        response = await client.put(root + ID, content=b"x" * 3_100_001, headers={"Content-Type": "application/json"})
        assert response.status_code == 413 and "no-store" in response.headers["cache-control"]
