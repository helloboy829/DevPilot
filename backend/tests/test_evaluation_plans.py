"""Synthetic-only frozen QA plan contracts and transaction boundaries."""

import json
import threading

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import event, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation import tables as t
from app.evaluation.datasets import QASample, SourceDeclaration
from app.evaluation.plan_repository import PlanRepository
from app.evaluation.plans import PlanCreate, PlanPreflightError
from app.evaluation.registry import ComponentLinkCreate, fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtection, RequestProtectionError
from app.evaluation.request_versions import RequestVersionCreate
from app.evaluation.schema import upgrade_evaluation_schema
from deerflow.persistence.models import ComponentRow


def limits(**changes):
    return {"mode": "effectiveness", "concurrency": 2, "request_count": 2, "timeout_ms": 1000, "wall_time_ms": 10000, "max_total_body_bytes": 10000, **changes}


def draft(version, dataset, **changes):
    return {
        "version_label": "Plan v1",
        "request_version_id": version["id"],
        "request_protected_hash": version["protected_hash"],
        "dataset_id": dataset["id"],
        "dataset_revision": dataset["revision"],
        "dataset_hash": dataset["content_hash"],
        "binding": {"schema": "qa-json-binding.v1", "input_pointer": "/q", "output_pointer": "/a"},
        "limits": limits(),
        "response_mode": "json_text",
        "confirmed": True,
        **changes,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"confirmed": 1},
        {"confirmed": False},
        {"scope": "approved"},
        {"response_mode": "sse"},
        {"version_label": "bad\nlabel"},
        {"request_protected_hash": "not-a-hash"},
        {"dataset_revision": True},
        {"binding": {"schema": "qa-json-binding.v1", "input_pointer": "", "output_pointer": "/a"}},
        {"binding": {"schema": "qa-json-binding.v1", "input_pointer": "/q", "output_pointer": "/a", "expected": "SYNTHETIC_GOLD"}},
        *[
            {"limits": limits(**value)}
            for value in [
                {"concurrency": 0},
                {"concurrency": 9},
                {"concurrency": True},
                {"request_count": 0},
                {"request_count": 10001},
                {"timeout_ms": 99},
                {"timeout_ms": 300001},
                {"wall_time_ms": 999},
                {"wall_time_ms": 3600001},
                {"max_total_body_bytes": 0},
                {"max_total_body_bytes": 67108865},
                {"mode": "unknown"},
                {"arbitrary_script": "SYNTHETIC"},
            ]
        ],
    ],
)
def test_plan_dto_is_bounded_explicit_and_rejects_unknown_configuration(change):
    with pytest.raises(ValidationError):
        PlanCreate.model_validate(draft({"id": "r", "protected_hash": "a" * 64}, {"id": "d", "revision": 2, "content_hash": "b" * 64}, **change))


def test_plan_paths_preserve_literal_spaces():
    data = draft({"id": "r", "protected_hash": "a" * 64}, {"id": "d", "revision": 2, "content_hash": "b" * 64})
    data["binding"]["input_pointer"] = "/ q "
    assert PlanCreate.model_validate(data).binding["input_pointer"] == "/ q "
    assert PlanCreate.model_validate({**data, "limits": limits(mode="performance", concurrency=64)}).limits.concurrency == 64


@pytest_asyncio.fixture
async def prepared(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'plans.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: ComponentRow.__table__.create(conn))
    await upgrade_evaluation_schema(engine)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf.begin() as session:
        session.add(ComponentRow(id="source", user_id="owner", name="Synthetic", transport="http_post", api_url="https://example.test", validation_type="manual_review"))
    repository = PlanRepository(sf, protection=RequestProtection(Fernet.generate_key()))
    project = await repository.create_project("owner", "Synthetic project")
    component = await repository.link_component("owner", project["id"], ComponentLinkCreate(source_component_id="source", kind="llm"))
    version = await repository.create_request_version(
        "owner",
        project["id"],
        component["id"],
        RequestVersionCreate(
            version_label="Request v1",
            confirmed=True,
            request={"url": "https://example.test/SYNTHETIC_PATH?key=SYNTHETIC_QUERY", "method": "POST", "headers": [["Authorization", "Bearer SYNTHETIC_SECRET"]], "body": '{"q":"placeholder","fixed":"SYNTHETIC_BODY"}'},
        ),
    )
    dataset = await repository.create_dataset("owner", project["id"], "Synthetic QA", "acceptance", SourceDeclaration(label="Synthetic", reference="synthetic://local", authorization_basis="Synthetic tests only", attested=True))
    data = await repository.replace_samples(
        "owner", project["id"], dataset["id"], dataset["revision"], [QASample(sample_id=identifier, input=question, expected="SYNTHETIC_GOLD", source_ref="synthetic://local") for identifier, question in [("z", "second"), ("a", "first")]]
    )
    dataset = await repository.freeze("owner", project["id"], dataset["id"], data["revision"], data["content_hash"])
    yield repository, engine, project["id"], component["id"], version, dataset
    await engine.dispose()


@pytest.mark.asyncio
async def test_frozen_plan_is_reproducible_metadata_only_and_append_only(prepared):
    repo, engine, project, component, version, dataset = prepared
    payload = PlanCreate.model_validate(draft(version, dataset))
    result = await repo.create_plan("owner", project, component, payload)
    assert result["scope"] == "frozen_definition_only"
    definition = result["definition"]
    assert definition["schema"] == "qa-json-plan.v1"
    assert definition["dataset_hash"] == dataset["content_hash"]
    assert definition["request_protected_hash"] == version["protected_hash"]
    assert definition["request_template_fingerprint"] == version["request_template"]["fingerprint"]
    assert definition["sample_order"] == "sample_id_ascending_cycle.v1"
    assert definition["evaluation_policy"] == "human_review_required.v1"
    assert result["definition_hash"] == fingerprint(definition)
    body_bytes = sum(len(json.dumps({"q": question, "fixed": "SYNTHETIC_BODY"}, separators=(",", ":")).encode()) for question in ("first", "second"))
    assert definition["preflight"] == {"sample_count": 2, "request_count": 2, "total_body_bytes": body_bytes}
    assert "SYNTHETIC" not in json.dumps(result)
    assert "encrypted_payload" not in json.dumps(result)
    assert await repo.get_plan("owner", project, result["id"]) == result
    assert await repo.list_plans("owner", project, component) == [result]
    assert [e["action"] for e in await repo.plan_audit("owner", project, result["id"])] == ["plan_frozen"]
    assert [e["action"] for e in await repo.request_version_audit("owner", project, version["id"])] == ["request_version_created", "request_version_opened"]
    payload.binding["input_pointer"] = "/changed"
    assert (await repo.get_plan("owner", project, result["id"]))["definition"] == definition
    await upgrade_evaluation_schema(engine)
    assert await repo.get_plan("owner", project, result["id"]) == result


@pytest.mark.asyncio
async def test_preflight_is_sorted_off_loop_input_only_and_performance_repeats_are_bounded(prepared, monkeypatch):
    from devpilot.qa_json_binding import QAJSONBinding

    repo, _, project, component, version, dataset = prepared
    loop_thread, calls = threading.get_ident(), []
    original = QAJSONBinding.render

    def track(binding, request, question):
        calls.append((threading.get_ident(), question))
        return original(binding, request, question)

    monkeypatch.setattr(QAJSONBinding, "render", track)
    result = await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset, limits=limits(mode="performance", request_count=5))))
    assert [value for _, value in calls] == ["first", "second"]
    assert all(thread != loop_thread for thread, _ in calls)
    assert result["definition"]["preflight"]["request_count"] == 5

    def size(q):
        return len(json.dumps({"q": q, "fixed": "SYNTHETIC_BODY"}, separators=(",", ":")).encode())

    assert result["definition"]["preflight"]["total_body_bytes"] == 3 * size("first") + 2 * size("second")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,error",
    [
        ({"dataset_revision": 999}, Conflict),
        ({"dataset_hash": "0" * 64}, Conflict),
        ({"request_protected_hash": "0" * 64}, Conflict),
        ({"binding": {"schema": "qa-json-binding.v1", "input_pointer": "/missing", "output_pointer": "/a"}}, PlanPreflightError),
        ({"limits": limits(request_count=1)}, PlanPreflightError),
        ({"limits": limits(max_total_body_bytes=1)}, PlanPreflightError),
        ({"limits": limits(mode="performance", request_count=1)}, PlanPreflightError),
    ],
)
async def test_failed_preflight_rolls_back_plan_and_internal_open_audit(prepared, change, error):
    repo, _, project, component, version, dataset = prepared
    with pytest.raises(error):
        await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset, **change)))
    assert await repo.list_plans("owner", project, component) == []
    assert len(await repo.request_version_audit("owner", project, version["id"])) == 1


@pytest.mark.asyncio
async def test_scope_is_checked_before_decryption_and_gold(prepared, monkeypatch):
    repo, _, project, component, version, dataset = prepared

    def forbidden(*_args):
        pytest.fail("No decryption before owner/project/component checks")

    monkeypatch.setattr(repo.protection, "open", forbidden)
    other = await repo.create_project("owner", "Other synthetic")
    for actor, pid, cid, changes in [
        ("intruder", project, component, {}),
        ("owner", other["id"], component, {}),
        ("owner", project, "missing", {}),
        ("owner", project, component, {"dataset_id": "missing"}),
        ("owner", project, component, {"request_version_id": "missing"}),
    ]:
        with pytest.raises(NotFound):
            await repo.create_plan(actor, pid, cid, PlanCreate.model_validate(draft(version, dataset, **changes)))


@pytest.mark.asyncio
async def test_duplicate_normalized_label_rolls_back_both_audits(prepared):
    repo, _, project, component, version, dataset = prepared
    result = await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset)))
    with pytest.raises(Conflict):
        await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset, version_label="PLAN   V1")))
    assert len(await repo.list_plans("owner", project, component)) == 1
    assert len(await repo.request_version_audit("owner", project, version["id"])) == 2
    assert len(await repo.plan_audit("owner", project, result["id"])) == 1


@pytest.mark.asyncio
async def test_tampered_gold_request_and_plan_fail_closed(prepared):
    repo, engine, project, component, version, dataset = prepared
    result = await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset)))
    async with engine.begin() as conn:
        await conn.execute(update(t.references).where(t.references.c.dataset_id == dataset["id"]).values(expected="SYNTHETIC_TAMPER"))
    with pytest.raises(Conflict):
        await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset, version_label="v2")))
    async with engine.begin() as conn:
        await conn.execute(update(t.references).where(t.references.c.dataset_id == dataset["id"]).values(expected="SYNTHETIC_GOLD"))
        await conn.execute(update(t.request_versions).where(t.request_versions.c.id == version["id"]).values(protected_hash="0" * 64))
    with pytest.raises(RequestProtectionError):
        await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft({**version, "protected_hash": "0" * 64}, dataset, version_label="v2")))
    async with engine.begin() as conn:
        await conn.execute(update(t.plans).where(t.plans.c.id == result["id"]).values(definition_hash="0" * 64))
    with pytest.raises(Conflict):
        await repo.get_plan("owner", project, result["id"])
    with pytest.raises(Conflict):
        await repo.list_plans("owner", project, component)


@pytest.mark.asyncio
async def test_metadata_is_readable_without_key_and_cross_owner_is_404(prepared):
    repo, _, project, component, version, dataset = prepared
    result = await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset)))
    repo.protection = None
    for owner in ("intruder",):
        for operation in (repo.get_plan(owner, project, result["id"]), repo.list_plans(owner, project, component), repo.plan_audit(owner, project, result["id"])):
            with pytest.raises(NotFound):
                await operation
    assert await repo.get_plan("owner", project, result["id"]) == result


@pytest.mark.asyncio
async def test_repository_revalidates_mutated_dto(prepared):
    repo, _, project, component, version, dataset = prepared
    payload = PlanCreate.model_validate(draft(version, dataset))
    payload.binding["expected"] = "SYNTHETIC_GOLD"
    with pytest.raises(ValidationError):
        await repo.create_plan("owner", project, component, payload)
    assert await repo.list_plans("owner", project, component) == []


@pytest.mark.asyncio
async def test_database_rejects_cross_component_request_and_audit(prepared):
    repo, engine, project, component, version, dataset = prepared
    result = await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset)))
    other_project = await repo.create_project("owner", "Other synthetic")
    async with engine.begin() as conn:
        await conn.execute(insert(t.project_components).values(id="other", project_id=project, source_component_id="source2", name_at_link="Synthetic", kind="llm", created_at="now"))
    async with engine.connect() as conn:
        row = dict((await conn.execute(select(t.plans).where(t.plans.c.id == result["id"]))).mappings().one())
        row.update(id="forged", component_id="other", label_key="new")
        with pytest.raises(IntegrityError):
            await conn.execute(insert(t.plans).values(**row))
        await conn.rollback()
        with pytest.raises(IntegrityError):
            await conn.execute(insert(t.plan_audit).values(id="forged", project_id=other_project["id"], plan_id=result["id"], actor="owner", action="plan_frozen", at="now"))
        await conn.rollback()
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0015"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["draft", "missing_reference", "oversize_input", "changed_template", "wrong_component"])
async def test_persisted_source_corruption_is_never_a_partial_plan(prepared, mutation):
    from sqlalchemy import delete

    repo, engine, project, component, version, dataset = prepared
    async with engine.begin() as conn:
        if mutation == "draft":
            await conn.execute(update(t.datasets).where(t.datasets.c.id == dataset["id"]).values(status="draft"))
        elif mutation == "missing_reference":
            await conn.execute(delete(t.references).where(t.references.c.dataset_id == dataset["id"], t.references.c.sample_id == "z"))
        elif mutation == "oversize_input":
            await conn.execute(update(t.samples).where(t.samples.c.dataset_id == dataset["id"]).values(input="x" * 10001))
        elif mutation == "changed_template":
            await conn.execute(update(t.request_versions).where(t.request_versions.c.id == version["id"]).values(request_template={"schema": "invalid"}))
        else:
            await conn.execute(insert(t.project_components).values(id="other", project_id=project, source_component_id="source2", name_at_link="Synthetic", kind="llm", created_at="now"))
            component = "other"
    expected = RequestProtectionError if mutation == "changed_template" else NotFound if mutation == "wrong_component" else Conflict
    with pytest.raises(expected):
        await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset)))
    assert await repo.list_plans("owner", project, component) == []
    assert len(await repo.request_version_audit("owner", project, version["id"])) == 1


@pytest.mark.asyncio
async def test_plan_metadata_reads_never_select_gold_or_request_ciphertext(prepared):
    repo, engine, project, component, version, dataset = prepared
    plan = await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset)))
    queries = []

    def track(_conn, _cursor, statement, _params, _ctx, _many):
        queries.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", track)
    try:
        await repo.get_plan("owner", project, plan["id"])
        await repo.list_plans("owner", project, component)
        await repo.plan_audit("owner", project, plan["id"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", track)
    assert queries and all("encrypted_payload" not in statement and "evaluation_references" not in statement and "evaluation_samples" not in statement for statement in queries)


@pytest.mark.asyncio
async def test_audit_insert_failure_rolls_back_plan_and_decryption_audit(prepared):
    repo, engine, project, component, version, dataset = prepared
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TRIGGER fail_plan_audit BEFORE INSERT ON evaluation_plan_audit BEGIN SELECT RAISE(ABORT, 'synthetic'); END"))
    with pytest.raises(Conflict):
        await repo.create_plan("owner", project, component, PlanCreate.model_validate(draft(version, dataset)))
    assert await repo.list_plans("owner", project, component) == []
    assert len(await repo.request_version_audit("owner", project, version["id"])) == 1


@pytest.mark.asyncio
async def test_upgrade_from_deployed_eval_0003_preserves_both_ledgers_and_ciphertext(tmp_path, monkeypatch):
    from app.evaluation import schema
    from app.evaluation.request_version_repository import RequestVersionRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'upgrade.db'}")
    original = schema.command.upgrade
    monkeypatch.setattr(schema.command, "upgrade", lambda config, _revision: original(config, "eval_0003"))
    try:
        await upgrade_evaluation_schema(engine)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        repository = RequestVersionRepository(sf, protection=RequestProtection(Fernet.generate_key()))
        project = await repository.create_project("owner", "Synthetic upgrade")
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
            await conn.execute(text("INSERT INTO alembic_version VALUES ('synthetic_harness')"))
            await conn.execute(insert(t.project_components).values(id="component", project_id=project["id"], source_component_id="source", name_at_link="Synthetic", kind="llm", created_at="now"))
        request = RequestVersionCreate(version_label="request", confirmed=True, request={"url": "https://example.test", "method": "POST", "headers": [], "body": '{"q":"SYNTHETIC_BODY"}'})
        version = await repository.create_request_version("owner", project["id"], "component", request)
        async with engine.connect() as conn:
            before = dict((await conn.execute(select(t.request_versions))).mappings().one())
        monkeypatch.setattr(schema.command, "upgrade", original)
        await upgrade_evaluation_schema(engine)
        await upgrade_evaluation_schema(engine)
        async with engine.connect() as conn:
            assert dict((await conn.execute(select(t.request_versions))).mappings().one()) == before
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "synthetic_harness"
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0015"
            assert not (await conn.execute(select(t.plans))).all()
        assert (await repository.open_request_version("owner", project["id"], version["id"])).body == request.request["body"]
    finally:
        await engine.dispose()
