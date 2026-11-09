"""Offline API-to-Worker acceptance chain, with only DNS/wire I/O replaced.

Uses migrated temporary SQLite and synthetic authentication/data/keys. This is
not a deployed/browser test, target authorization, formal approval or a model
call. No repository inserts seed plans, executions, outputs, reviews or archives.
"""

import asyncio
import io
import json
import socket
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select
from test_evaluation_registry_router import api as api

from app.evaluation import http as outbound
from app.evaluation import tables as t
from app.evaluation.execution import (
    ExecutionPolicy,
    ExecutionRepository,
    QAExecutionWorker,
)
from app.evaluation.report_docx import DOCX_MIME, RENDERER_ID

INPUTS = [f"SYNTHETIC_INPUT_CANARY_{i}" for i in range(1, 4)]
GOLD = [f"SYNTHETIC_GOLD_CANARY_{i}" for i in range(1, 4)]
OUTPUTS = [f"SYNTHETIC_OUTPUT_CANARY_{i}" for i in range(1, 4)]
SECRET = "SYNTHETIC_REQUEST_SECRET"
NOTE = "SYNTHETIC_REVIEW_NOTE"
WIRE_ERROR = "SYNTHETIC_WIRE_ERROR"
CANARIES = [*INPUTS, *GOLD, *OUTPUTS, SECRET, NOTE, WIRE_ERROR]


def response_json(response, status=200, *, sensitive=False):
    assert response.status_code == status, response.text
    assert "no-store" in response.headers["cache-control"]
    if not sensitive:
        assert all(value not in response.text for value in CANARIES)
        assert "encrypted_payload" not in response.text
        assert "claim_hash" not in response.text
    return response.json()


class Body(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content
        self.closed = False

    async def __aiter__(self):
        yield self.content

    async def aclose(self):
        self.closed = True


@pytest_asyncio.fixture
async def workflow(api, monkeypatch):
    client, app, base, _ = api
    # Explicitly test-only, never a configuration fallback or a deployed key.
    monkeypatch.setenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", Fernet.generate_key().decode())
    dataset = response_json(
        await client.post(
            base + "/datasets",
            json={
                "name": "Three-case benchmark",
                "purpose": "baseline",
                "source": {
                    "label": "Synthetic fixture",
                    "reference": "fixture:workflow",
                    "authorization_basis": "Owned synthetic",
                    "attested": True,
                },
            },
        )
    )
    path = base + "/datasets/" + dataset["id"]
    content = "\n".join(
        json.dumps(
            {
                "sample_id": f"q{i}",
                "input": prompt,
                "expected": expected,
                "source_ref": f"fixture:{i}",
            }
        )
        for i, (prompt, expected) in enumerate(zip(INPUTS, GOLD, strict=True), 1)
    )
    dataset = response_json(
        await client.put(
            path + "/samples",
            json={"revision": 1, "format": "jsonl", "content": content},
        )
    )
    dataset = response_json(
        await client.post(
            path + "/freeze",
            json={
                "revision": 2,
                "content_hash": dataset["content_hash"],
                "reviewed": True,
            },
        )
    )
    component = response_json(await client.post(base + "/components", json={"source_component_id": "c1", "kind": "agent"}))
    clock = {"ms": 1_800_000_000_000}
    config = SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"]})
    repository = ExecutionRepository(
        app.state.evaluation_repo.sf,
        policy=ExecutionPolicy(enabled=True, max_response_bytes=256),
        config_getter=lambda: config,
        clock_ms=lambda: clock["ms"],
    )
    await repository.initialize()
    app.state.evaluation_execution_repo = repository
    state = SimpleNamespace(
        client=client,
        app=app,
        base=base,
        dataset=dataset,
        component=component,
        clock=clock,
        repository=repository,
        worker=QAExecutionWorker(repository, lambda: config),
        fault=None,
        run_id=None,
        sent=[],
        dns=[],
        bodies=[],
    )

    async def resolve(host, port, **kwargs):
        assert host == "example.test" and port == 443
        assert kwargs["type"] == socket.SOCK_STREAM
        state.dns.append((host, port))
        ip = "127.0.0.1" if state.fault == "policy_rejected" and len(state.dns) == 2 else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]

    async def wire(request):
        # The real shared transport must validate DNS and pin Host/SNI first.
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "example.test"
        assert request.extensions["sni_hostname"] == "example.test"
        assert request.headers["authorization"] == "Bearer " + SECRET
        assert request.headers["accept-encoding"] == "identity"
        body = json.loads(request.content)
        assert set(body) == {"q", "build"}
        assert body["build"] == state.active_build
        ordinal = INPUTS.index(body["q"]) + 1
        assert not any(value.encode() in request.content for value in GOLD)
        # Observe the committed journal from a DIFFERENT DB session before I/O.
        async with repository.sf() as session:
            dispatch = (
                (
                    await session.execute(
                        select(t.dispatches).where(
                            t.dispatches.c.run_id == state.run_id,
                            t.dispatches.c.ordinal == ordinal,
                        )
                    )
                )
                .mappings()
                .one()
            )
            execution = (await session.execute(select(t.executions).where(t.executions.c.run_id == state.run_id))).mappings().one()
        assert dispatch["state"] == "dispatched" and dispatch["ticket_hash"]
        assert execution["state"] == "running" and execution["reservation_held"]
        assert (state.run_id, ordinal) not in state.sent
        state.sent.append((state.run_id, ordinal))
        fault = state.fault if ordinal == 2 else None
        if fault == "delivery_unknown":
            raise httpx.ReadTimeout(WIRE_ERROR, request=request)
        content = json.dumps({"a": OUTPUTS[ordinal - 1]}).encode()
        if fault == "invalid_output":
            content = b'{"a":'
        elif fault == "response_limit":
            content = b"x" * 1000
        stream = Body(content)
        state.bodies.append(stream)
        return httpx.Response(
            502 if fault == "http_error" else 200,
            headers={"content-type": "text/event-stream" if fault == "unsupported_response" else "application/json"},
            stream=stream,
        )

    def transport(**kwargs):
        assert kwargs == {"verify": True, "trust_env": False, "retries": 0}
        return httpx.MockTransport(wire)

    def forbidden_network(*args, **kwargs):
        raise AssertionError("Unexpected real network use in offline QA workflow")

    # Even a future bypass of the shared transport cannot reach a real target.
    monkeypatch.setattr(socket, "getaddrinfo", forbidden_network)
    for method in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, method, forbidden_network)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(outbound.httpx, "AsyncHTTPTransport", transport)
    return state


async def create_plan(state, build, *, threshold=6667, concurrency=1):
    root = state.base + "/components/" + state.component["id"]
    version = response_json(
        await state.client.post(
            root + "/request-versions",
            json={
                "version_label": "Request " + build,
                "confirmed": True,
                "request": {
                    "url": "https://example.test/qa",
                    "method": "POST",
                    "headers": [["Authorization", "Bearer " + SECRET]],
                    "body": json.dumps({"q": "placeholder", "build": build}),
                },
            },
        )
    )
    dataset = state.dataset
    return response_json(
        await state.client.post(
            root + "/plans",
            json={
                "version_label": "Plan " + build,
                "request_version_id": version["id"],
                "request_protected_hash": version["protected_hash"],
                "dataset_id": dataset["id"],
                "dataset_revision": dataset["revision"],
                "dataset_hash": dataset["content_hash"],
                "binding": {
                    "schema": "qa-json-binding.v1",
                    "input_pointer": "/q",
                    "output_pointer": "/a",
                },
                "limits": {
                    "mode": "effectiveness",
                    "concurrency": concurrency,
                    "request_count": 3,
                    "timeout_ms": 1000,
                    "wall_time_ms": 10000,
                    "max_total_body_bytes": 10000,
                },
                "response_mode": "json_text",
                "acceptance_criteria": {
                    "schema": "qa-effectiveness-criteria.v1",
                    "version_label": "Frozen criteria",
                    "min_pass_rate_bps": threshold,
                },
                "confirmed": True,
            },
        )
    )


async def collect(state, plan, *, build):
    state.active_build = build
    path = state.base + "/execution-runs/" + uuid4().hex
    payload = {
        "plan_id": plan["id"],
        "plan_hash": plan["definition_hash"],
        "confirmed": True,
        "target_authorized": True,
    }
    before = len(state.sent)
    queued = response_json(await state.client.put(path, json=payload))
    assert queued["state"] == "queued" and queued["reservation_held"]
    # API admission alone does not send; same-ID receipt is not a new dispatch.
    assert response_json(await state.client.get(path)) == queued
    assert response_json(await state.client.put(path, json=payload)) == queued
    assert len(state.sent) == before
    state.run_id = queued["run_id"]
    assert await state.worker.run_once() is True
    finished = response_json(await state.client.get(path))
    assert not finished["reservation_held"]
    assert response_json(await state.client.put(path, json=payload)) == finished
    assert await state.worker.run_once() is False
    assert all(body.closed for body in state.bodies)
    return state.base + "/review-runs/" + queued["run_id"], finished


def archive_payload(summary):
    return {
        "title": "Synthetic verified draft",
        "template_id": "verified-qa-project-en",
        "template_version": "1.1.0",
        "sources": [{"run_id": summary["run_id"], "summary_hash": summary["summary_hash"]}],
        "confirmed": True,
    }


async def review(state, root, ordinal, decision, *, revision=0):
    case = response_json(await state.client.get(root + f"/cases/{ordinal}"), sensitive=True)
    assert case["input"] == INPUTS[ordinal - 1] and case["expected"] == GOLD[ordinal - 1]
    payload = {
        "case_hash": case["case_hash"],
        "expected_revision": revision,
        "decision": decision,
        "note": NOTE,
        "confirmed": True,
    }
    response = await state.client.post(root + f"/cases/{ordinal}/reviews", json=payload)
    return case, payload, response


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_api_worker_review_report_word_and_same_benchmark_retest(workflow, monkeypatch, concurrency):
    state, summaries, roots, archives = workflow, [], [], []
    # Save BOTH versions before executing v1: the Worker must not use latest.
    plans = {build: await create_plan(state, build, concurrency=concurrency) for build in ("v1", "v2")}
    for build, decisions, expected_status in (
        ("v1", ["pass", "fail", "pass"], "not_met"),
        ("v2", ["pass"] * 3, "met"),
    ):
        state.clock["ms"] += 1000  # Distinct frozen chronology; no sleep/timing contract.
        plan = plans[build]
        assert plan["definition"]["schema"] == "qa-json-plan.v2"
        root, execution = await collect(state, plan, build=build)
        assert execution["state"] == "collected"  # Collection is NOT a verdict.
        roots.append(root)
        metadata = response_json(await state.client.get(root + "/cases"))
        assert len(metadata["cases"]) == 3
        pending = response_json(await state.client.get(root + "/summary"))
        assert pending["human_pass_rate"] == {
            "numerator": 0,
            "denominator": 3,
            "value": 0,
        }
        assert pending["criteria_evaluation"]["status"] == "incomplete"
        assert pending["counts"]["unreviewed"] == 3
        response_json(
            await state.client.put(
                state.base + "/report-archives/" + uuid4().hex,
                json=archive_payload(pending),
            ),
            409,
        )
        for ordinal, decision in enumerate(decisions, 1):
            case, payload, response = await review(state, root, ordinal, decision)
            assert case["output"] == OUTPUTS[ordinal - 1]
            assert response_json(response)["revision"] == 1
            response_json(
                await state.client.post(root + f"/cases/{ordinal}/reviews", json=payload),
                409,
            )
        summary = response_json(await state.client.get(root + "/summary"))
        assert summary["readiness"] == "review_complete" and not summary["blockers"]
        assert summary["human_pass_rate"] == {
            "numerator": decisions.count("pass"),
            "denominator": 3,
            "value": decisions.count("pass") / 3,
        }
        assert summary["criteria_evaluation"]["status"] == expected_status
        assert summary["acceptance"] == summary["criteria_evaluation"]["approval"] == "not_approved"
        summaries.append(summary)
        path = state.base + "/report-archives/" + uuid4().hex
        payload = archive_payload(summary)
        saved = response_json(await state.client.put(path, json=payload))
        assert saved["template"]["version"] == "1.1.0" and saved["acceptance"] == "not_approved"
        assert saved["components"] == [summary]
        archives.append((path, saved))

    comparison_path = state.base + "/retest-archives/" + uuid4().hex
    comparison_payload = {side: {"run_id": summary["run_id"], "summary_hash": summary["summary_hash"]} for side, summary in zip(("baseline", "retest"), summaries, strict=True)}
    comparison_payload["confirmed"] = True
    comparison = response_json(await state.client.put(comparison_path, json=comparison_payload))
    assert comparison["transitions"] == {
        "fail_to_pass": 1,
        "pass_to_fail": 0,
        "pass_to_pass": 2,
        "fail_to_fail": 0,
    }
    assert comparison["pass_rate_delta"] == {
        "numerator": 1,
        "denominator": 3,
        "value": 1 / 3,
    }
    assert comparison["request_definition_changed"] and comparison["acceptance"] == "not_approved"

    # New current decisions do not rewrite frozen reports or comparisons.
    _, _, response = await review(state, roots[0], 2, "pass", revision=1)
    assert response_json(response)["revision"] == 2
    revised = response_json(await state.client.get(roots[0] + "/summary"))
    assert revised["summary_hash"] != summaries[0]["summary_hash"]
    assert revised["criteria_evaluation"]["status"] == "met"
    response_json(
        await state.client.put(
            state.base + "/report-archives/" + uuid4().hex,
            json=archive_payload(summaries[0]),
        ),
        409,
    )
    response_json(
        await state.client.put(state.base + "/retest-archives/" + uuid4().hex, json=comparison_payload),
        409,
    )
    assert response_json(await state.client.get(comparison_path)) == comparison
    assert response_json(await state.client.put(comparison_path, json=comparison_payload)) == comparison

    # Sensitive persisted fields are ciphertext, not public/source substitutes.
    async with state.repository.sf() as session:
        for table, count in (
            (t.request_versions, 2),
            (t.output_evidence, 6),
            (t.case_reviews, 7),
        ):
            tokens = list((await session.execute(select(table.c.encrypted_payload))).scalars())
            assert len(tokens) == count and all(token.startswith("gAAAA") for token in tokens)
            assert all(value not in token for token in tokens for value in CANARIES)

    path, saved = archives[1]
    url = path + "/exports/" + RENDERER_ID + "?archive_hash=" + saved["archive_hash"]
    word = await state.client.get(url)
    assert word.status_code == 200 and word.headers["content-type"] == DOCX_MIME
    assert "no-store" in word.headers["cache-control"]
    with zipfile.ZipFile(io.BytesIO(word.content)) as package:
        xml = package.read("word/document.xml").decode()
    assert saved["archive_hash"] in xml and "Frozen effectiveness criteria" in xml
    assert all(value not in xml for value in CANARIES)
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    monkeypatch.setattr("app.evaluation.qa_reports.archive_templates", lambda: [])
    for path, saved in archives:
        assert response_json(await state.client.get(path)) == saved
    assert response_json(await state.client.get(comparison_path)) == comparison
    assert (await state.client.get(url)).content == word.content
    response_json(await state.client.get(roots[0] + "/cases/1"), 503)
    for actor, internal, status in ((2, False, 404), (1, True, 403), (0, False, 401)):
        state.app.state.actor, state.app.state.internal = actor, internal
        for target in (archives[0][0], comparison_path, url):
            response_json(await state.client.get(target), status)
    assert len(state.sent) == len(set(state.sent)) == len(state.dns) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "http_error",
        "invalid_output",
        "response_limit",
        "unsupported_response",
        "delivery_unknown",
        "policy_rejected",
    ],
)
async def test_wire_failures_never_retry_shrink_denominator_or_approve_missing_evidence(workflow, caplog, fault):
    state = workflow
    state.fault = fault
    plan = await create_plan(state, "v1", threshold=0)
    root, execution = await collect(state, plan, build="v1")
    assert execution["state"] == ("interrupted" if fault == "delivery_unknown" else "collected")
    expected_sent = 2 if fault in {"delivery_unknown", "policy_rejected"} else 3
    assert len(state.sent) == len(set(state.sent)) == expected_sent
    assert len(state.dns) == (2 if fault == "delivery_unknown" else 3)
    metadata = response_json(await state.client.get(root + "/cases"))
    assert len(metadata["cases"]) == 3
    for ordinal in range(1, 4):
        case = response_json(await state.client.get(root + f"/cases/{ordinal}"), sensitive=True)
        if ordinal == 2:
            assert case["output"] is None and case["technical"]["kind"] == fault
            if fault == "response_limit":
                assert case["technical"]["body_bytes"] == 257
        if ordinal == 3 and fault == "delivery_unknown":
            assert case["state"] == "not_dispatched" and case["output"] is None
        if case["output"] is None:
            _, _, rejected = await review(state, root, ordinal, "pass")
            response_json(rejected, 409)
            decision = "uncertain"
        else:
            decision = "pass"
        _, _, accepted = await review(state, root, ordinal, decision)
        assert response_json(accepted)["revision"] == 1
    summary = response_json(await state.client.get(root + "/summary"))
    collected = 1 if fault == "delivery_unknown" else 2
    assert summary["human_pass_rate"] == {
        "numerator": collected,
        "denominator": 3,
        "value": collected / 3,
    }
    assert summary["technical_counts"] == {
        "collected": collected,
        "other": 3 - collected,
    }
    assert summary["counts"] == {
        "pass": collected,
        "fail": 0,
        "uncertain": 3 - collected,
        "unreviewed": 0,
    }
    assert summary["readiness"] == "provisional"
    assert {"technical_incomplete", "uncertain"}.issubset(summary["blockers"])
    assert summary["criteria_evaluation"]["status"] == "incomplete"
    assert summary["acceptance"] == "not_approved"
    response_json(
        await state.client.put(
            state.base + "/report-archives/" + uuid4().hex,
            json=archive_payload(summary),
        ),
        409,
    )
    assert response_json(await state.client.get(state.base + "/report-archives"))["archives"] == []
    assert await state.worker.run_once() is False
    assert len(state.sent) == expected_sent and all(body.closed for body in state.bodies)
    assert all(value not in caplog.text for value in CANARIES)
