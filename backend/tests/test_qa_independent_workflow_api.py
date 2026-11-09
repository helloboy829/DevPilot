"""Offline HTTP/real-Worker independent lifecycle; only DNS/wire is synthetic.

No direct inserts seed plans, outputs, tasks, decisions, assessments or archives.
Synthetic identities/keys and a migrated temporary SQLite are not deployed auth,
independent pre-run admission, formal approval or real target/model acceptance.
"""

import io
import zipfile
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from test_evaluation_registry_router import api as api
from test_qa_workflow_api import CANARIES, GOLD, INPUTS, NOTE, OUTPUTS, collect, create_plan, response_json, review
from test_qa_workflow_api import workflow as workflow

from app.evaluation.independent_report_docx import DOCX_MIME, RENDERER_ID
from app.evaluation.qa_independent_archives import IndependentReportRepository
from app.gateway.auth.models import User
from app.gateway.routers import evaluation_review_tasks as routes

A, B, ARB = [str(UUID(int=i)) for i in (2, 3, 4)]
TASK_ROOT = "/api/evaluation/review-tasks/"


@pytest_asyncio.fixture
async def independent(workflow, monkeypatch):
    state = workflow
    state.app.include_router(routes.router)
    state.app.include_router(routes.project_router)
    users = {key: User(id=UUID(key), email=f"synthetic-{i}@example.com") for i, key in enumerate((A, B, ARB))}

    async def get_user(key):
        return users.get(key)

    monkeypatch.setattr(routes, "get_local_provider", lambda: SimpleNamespace(get_user=get_user))
    return state


def source(assessment):
    return {
        "run_id": assessment["run_id"],
        "summary_hash": assessment["assessment"]["summary_hash"],
        "assessment_id": assessment["id"],
        "assessment_revision": assessment["revision"],
        "assessment_hash": assessment["assessment_hash"],
    }


def report_payload(assessment):
    return {
        "title": "Synthetic independent historical draft",
        "template_id": "independent-qa-project-en",
        "template_version": "1.0.0",
        "sources": [source(assessment)],
        "confirmed": True,
    }


async def task_payload(state, root, ordinal):
    state.app.state.actor = 1
    case = response_json(await state.client.get(root + f"/cases/{ordinal}"), sensitive=True)
    assert case["input"] == INPUTS[ordinal - 1] and case["expected"] == GOLD[ordinal - 1]
    return {
        "run_id": root.rsplit("/", 1)[1],
        "ordinal": ordinal,
        "case_hash": case["case_hash"],
        "reviewer_ids": [A, B],
        "arbitrator_id": ARB,
        "share_reference": True,
        "confirmed": True,
    }, case


async def vote(state, task_id, actor, outcome, *, missing=False):
    state.app.state.actor = actor
    path = TASK_ROOT + task_id
    task = response_json(await state.client.get(path))
    claimed = response_json(await state.client.post(path + "/claim", json={"expected_revision": task["revision"], "confirmed": True}))
    opened = response_json(await state.client.get(path + "/case"), sensitive=True)
    ordinal = opened["ordinal"]
    assert opened["input"] == INPUTS[ordinal - 1]
    assert opened["expected"] == GOLD[ordinal - 1]
    assert opened["output"] == (None if missing else OUTPUTS[ordinal - 1])
    assert len(opened["prior_decisions"]) == (2 if actor == 4 else 0)
    payload = {"expected_revision": claimed["revision"], "subject_hash": claimed["subject_hash"], "confirmed": True, "decision": outcome, "note": NOTE}
    if missing:
        # Even after an explicit sensitive open, a technical gap cannot PASS.
        response_json(await state.client.post(path + "/decisions", json={**payload, "decision": "pass"}), 409)
    return response_json(await state.client.post(path + "/decisions", json=payload))


async def resolve_case(state, root, ordinal, outcome, *, disagreement=False):
    payload, case = await task_payload(state, root, ordinal)
    task_id = uuid4().hex
    response_json(await state.client.post(state.base + "/review-tasks/" + task_id, json=payload))
    missing = case["output"] is None
    first = await vote(state, task_id, 2, "pass" if disagreement else outcome, missing=missing)
    assert first["status"] == "in_review"
    second = await vote(state, task_id, 3, outcome, missing=missing)
    if disagreement or outcome == "uncertain":
        assert second["status"] == "escalated"
        final = await vote(state, task_id, 4, outcome, missing=missing)
    else:
        final = second
    assert final["status"] == ("escalated" if outcome == "uncertain" else "resolved")
    state.app.state.actor = 1
    result = response_json(await state.client.get(TASK_ROOT + task_id + "/result"), sensitive=True)
    assert all(decision["note"] == NOTE for decision in result["decisions"])
    assert result["resolution"]["outcome"] == outcome
    assert result["resolution"]["approval"] == "not_approved"
    return task_id, result


async def save_assessment(state, root, *, previous=0):
    preview = response_json(await state.client.get(root + "/independent-assessment"))
    path = root + "/assessments/" + uuid4().hex
    payload = {"summary_hash": preview["summary_hash"], "expected_previous_revision": previous, "confirmed": True}
    saved = response_json(await state.client.post(path, json=payload))
    assert saved["revision"] == previous + 1 and saved["assessment"] == preview
    assert response_json(await state.client.get(path)) == saved
    return path, saved


async def complete_run(state, build):
    plan = await create_plan(state, build)
    state.clock["ms"] += 1000
    root, _ = await collect(state, plan, build=build)
    for ordinal in range(1, 4):
        await resolve_case(state, root, ordinal, "pass")
    _, saved = await save_assessment(state, root)
    return root, saved


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_worker_blind_review_assessment_historical_report_word_and_retest(independent, monkeypatch, caplog, concurrency):
    state, roots, assessments, reports, task_ids = independent, [], [], [], []
    # BOTH versions exist before v1 executes. The wire verifies the frozen build.
    plans = {build: await create_plan(state, build, concurrency=concurrency) for build in ("v1", "v2")}
    for build, outcomes, status in (("v1", ["pass", "fail", "pass"], "not_met"), ("v2", ["pass"] * 3, "met")):
        state.clock["ms"] += 1000
        root, execution = await collect(state, plans[build], build=build)
        roots.append(root)
        assert execution["state"] == "collected"
        if build == "v1":
            # All owner votes PASS; none may count as an independent decision.
            for ordinal in range(1, 4):
                _, _, accepted = await review(state, root, ordinal, "pass")
                response_json(accepted)
        pending = response_json(await state.client.get(root + "/independent-assessment"))
        assert pending["counts"] == {"pass": 0, "fail": 0, "uncertain": 0, "unreviewed": 3}
        assert pending["human_pass_rate"] == {"numerator": 0, "denominator": 3, "value": 0}
        assert pending["criteria_evaluation"]["status"] == "incomplete"
        for ordinal, outcome in enumerate(outcomes, 1):
            task_id, _ = await resolve_case(state, root, ordinal, outcome, disagreement=build == "v1" and ordinal == 2)
            task_ids.append(task_id)
        path, assessment = await save_assessment(state, root)
        preview = assessment["assessment"]
        assert preview["counts"] == {"pass": outcomes.count("pass"), "fail": outcomes.count("fail"), "uncertain": 0, "unreviewed": 0}
        assert preview["human_pass_rate"] == {"numerator": outcomes.count("pass"), "denominator": 3, "value": outcomes.count("pass") / 3}
        assert preview["criteria_evaluation"]["status"] == status
        assert preview["readiness"] == "review_complete" and preview["blockers"] == []
        assert preview["acceptance"] == preview["criteria_evaluation"]["approval"] == "not_approved"
        assessments.append((path, assessment))
        legacy = response_json(await state.client.get(root + "/summary"))
        assert legacy["counts"]["pass"] == (3 if build == "v1" else 0)
        assert legacy["counts"]["unreviewed"] == (0 if build == "v1" else 3)
        report_path = state.base + "/independent-report-archives/" + uuid4().hex
        report = response_json(await state.client.put(report_path, json=report_payload(assessment)))
        assert report["components"][0]["assessment_ref"] == {key: source(assessment)[key] for key in ("assessment_id", "assessment_revision", "assessment_hash")}
        assert report["components"][0]["counts"] == preview["counts"]
        assert report["acceptance"] == "not_approved"
        reports.append((report_path, report))
    comparison_path = state.base + "/independent-retest-archives/" + uuid4().hex
    comparison_payload = {"baseline": source(assessments[0][1]), "retest": source(assessments[1][1]), "confirmed": True}
    comparison = response_json(await state.client.put(comparison_path, json=comparison_payload))
    assert comparison["transitions"] == {"fail_to_pass": 1, "pass_to_fail": 0, "pass_to_pass": 2, "fail_to_fail": 0}
    assert comparison["pass_rate_delta"] == {"numerator": 1, "denominator": 3, "value": 1 / 3}
    assert [case["ordinal"] for case in comparison["cases"]] == [1, 2, 3]
    assert comparison["acceptance"] == "not_approved" and comparison["request_definition_changed"]
    assert response_json(await state.client.get(state.base + "/report-archives"))["archives"] == []
    assert response_json(await state.client.get(state.base + "/retest-archives"))["comparisons"] == []
    # Assignment is a narrow case grant, never project membership or owner access.
    state.app.state.actor = 2
    for target in (state.base + "/datasets", roots[0] + "/cases/1", assessments[0][0], reports[0][0], comparison_path):
        response_json(await state.client.get(target), 404)
    response_json(await state.client.get(TASK_ROOT + task_ids[0] + "/result"), 404)
    state.app.state.actor = 5
    response_json(await state.client.get(TASK_ROOT + task_ids[0]), 404)
    state.app.state.actor = 1
    task_path = TASK_ROOT + task_ids[0]
    old_round = response_json(await state.client.get(task_path + "/result"), sensitive=True)
    task = response_json(await state.client.get(task_path))
    reopened = response_json(await state.client.post(task_path + "/reopen", json={"expected_revision": task["revision"], "confirmed": True, "reason": NOTE}))
    assert reopened["round"] == 2
    assert response_json(await state.client.get(task_path + "/result?round_number=1"), sensitive=True) == old_round
    _, incomplete = await save_assessment(state, roots[0], previous=1)
    assert incomplete["assessment"]["readiness"] == "provisional"
    assert incomplete["assessment"]["counts"]["unreviewed"] == 1
    assert incomplete["assessment"]["human_pass_rate"]["denominator"] == 3
    response_json(await state.client.put(state.base + "/independent-report-archives/" + uuid4().hex, json=report_payload(incomplete)), 409)
    response_json(await state.client.put(state.base + "/independent-retest-archives/" + uuid4().hex, json={**comparison_payload, "baseline": source(incomplete)}), 409)
    # Explicit historical complete IDs remain stageable despite the reopened task.
    historical = response_json(await state.client.put(state.base + "/independent-report-archives/" + uuid4().hex, json=report_payload(assessments[0][1])))
    assert historical["components"] == reports[0][1]["components"]
    # The same assessment pair is unique; a new ID must not duplicate it.
    response_json(await state.client.put(state.base + "/independent-retest-archives/" + uuid4().hex, json=comparison_payload), 409)
    _, second_revision = await save_assessment(state, roots[1], previous=1)
    historical_retest = response_json(await state.client.put(state.base + "/independent-retest-archives/" + uuid4().hex, json={**comparison_payload, "retest": source(second_revision)}))
    assert historical_retest["cases"] == comparison["cases"]
    url = reports[0][0] + "/exports/" + RENDERER_ID + "?archive_hash=" + reports[0][1]["archive_hash"]
    word = await state.client.get(url)
    assert word.status_code == 200 and word.headers["content-type"] == DOCX_MIME
    assert "no-store" in word.headers["cache-control"]
    with zipfile.ZipFile(io.BytesIO(word.content)) as package:
        xml = package.read("word/document.xml").decode()
    assert reports[0][1]["archive_hash"] in xml and assessments[0][1]["id"] in xml
    assert all(value not in xml for value in CANARIES)

    def forbidden(*args, **kwargs):
        raise AssertionError("Stored historical reads/exports must not reopen sources or current templates")

    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    monkeypatch.setattr(IndependentReportRepository, "templates", forbidden)
    monkeypatch.setattr(IndependentReportRepository, "_source_snapshot", forbidden)
    for path, saved in (*assessments, *reports):
        assert response_json(await state.client.get(path)) == saved
    assert response_json(await state.client.get(comparison_path)) == comparison
    assert (await state.client.get(url)).content == word.content
    response_json(await state.client.get(roots[0] + "/cases/1"), 503)
    assert len(state.sent) == len(set(state.sent)) == len(state.dns) == 6
    assert await state.worker.run_once() is False
    assert all(value not in caplog.text for value in CANARIES)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["http_error", "invalid_output", "response_limit", "unsupported_response", "delivery_unknown", "policy_rejected"])
async def test_independent_technical_gaps_block_even_zero_threshold_without_resend(independent, caplog, fault):
    state = independent
    state.fault = fault
    plan = await create_plan(state, "v1", threshold=0)
    root, execution = await collect(state, plan, build="v1")
    assert execution["state"] == ("interrupted" if fault == "delivery_unknown" else "collected")
    expected_sent = 2 if fault in {"delivery_unknown", "policy_rejected"} else 3
    for ordinal in range(1, 4):
        case = response_json(await state.client.get(root + f"/cases/{ordinal}"), sensitive=True)
        if ordinal == 2:
            assert case["output"] is None and case["technical"]["kind"] == fault
        await resolve_case(state, root, ordinal, "uncertain" if case["output"] is None else "pass")
    _, assessment = await save_assessment(state, root)
    summary = assessment["assessment"]
    collected = 1 if fault == "delivery_unknown" else 2
    assert summary["counts"] == {"pass": collected, "fail": 0, "uncertain": 3 - collected, "unreviewed": 0}
    assert summary["human_pass_rate"] == {"numerator": collected, "denominator": 3, "value": collected / 3}
    assert summary["technical_counts"] == {"collected": collected, "other": 3 - collected}
    assert {"technical_incomplete", "uncertain"}.issubset(summary["blockers"])
    assert summary["readiness"] == "provisional" and summary["criteria_evaluation"]["status"] == "incomplete"
    assert summary["acceptance"] == "not_approved"
    response_json(await state.client.put(state.base + "/independent-report-archives/" + uuid4().hex, json=report_payload(assessment)), 409)
    assert response_json(await state.client.get(state.base + "/independent-report-archives"))["archives"] == []
    assert response_json(await state.client.get(root + "/summary"))["counts"]["unreviewed"] == 3
    assert await state.worker.run_once() is False
    assert len(state.sent) == len(set(state.sent)) == expected_sent
    assert len(state.dns) == (2 if fault == "delivery_unknown" else 3)
    assert all(body.closed for body in state.bodies)
    assert all(value not in caplog.text for value in CANARIES)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["task", "assessment", "report", "retest"])
@pytest.mark.parametrize("committed", [False, True])
async def test_lost_http_write_response_only_gets_same_id_never_resends(independent, monkeypatch, kind, committed):
    state = independent
    if kind == "task":
        root, _ = await collect(state, await create_plan(state, "v1"), build="v1")
        payload, _ = await task_payload(state, root, 1)
        task_id = uuid4().hex
        path, receipt, method = state.base + "/review-tasks/" + task_id, TASK_ROOT + task_id, "POST"
    elif kind == "assessment":
        root, _ = await collect(state, await create_plan(state, "v1"), build="v1")
        for ordinal in range(1, 4):
            await resolve_case(state, root, ordinal, "pass")
        preview = response_json(await state.client.get(root + "/independent-assessment"))
        payload = {"summary_hash": preview["summary_hash"], "expected_previous_revision": 0, "confirmed": True}
        path = receipt = root + "/assessments/" + uuid4().hex
        method = "POST"
    else:
        _, first = await complete_run(state, "v1")
        method = "PUT"
        path = receipt = state.base + "/independent-" + kind + "-archives/" + uuid4().hex
        if kind == "report":
            payload = report_payload(first)
        else:
            _, second = await complete_run(state, "v2")
            payload = {"baseline": source(first), "retest": source(second), "confirmed": True}
    original, requests = state.client.send, []
    sends_before = list(state.sent)

    async def lost_response(request, **kwargs):
        requests.append((request.method, request.url.path))
        if request.method == method and request.url.path == path:
            if committed:
                response_json(await original(request, **kwargs))
            raise httpx.ReadError("Synthetic lost response", request=request)
        return await original(request, **kwargs)

    monkeypatch.setattr(state.client, "send", lost_response)
    with pytest.raises(httpx.ReadError):
        await state.client.request(method, path, json=payload)
    found = response_json(await state.client.get(receipt), 200 if committed else 404)
    if committed:
        assert found["id"] == path.rsplit("/", 1)[1]
    assert requests == [(method, path), ("GET", receipt)]
    assert state.sent == sends_before and len(state.sent) == len(set(state.sent))
    # A 404 is an unresolved write outcome, not permission to create/resend.
