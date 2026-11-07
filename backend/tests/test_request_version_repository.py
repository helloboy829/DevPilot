"""Synthetic append-only request version persistence and migration contracts."""

import hashlib
import json

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation import tables as t
from app.evaluation.registry import ComponentLinkCreate
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtection, RequestProtectionError
from app.evaluation.request_version_repository import RequestVersionRepository
from app.evaluation.request_versions import RequestVersionCreate
from app.evaluation.schema import upgrade_evaluation_schema
from deerflow.persistence.component_tests.model import ComponentRow


def payload(label="v1"):
    return RequestVersionCreate(
        version_label=label, confirmed=True, request={"url": "https://example.test/SYNTHETIC_PATH?token=SYNTHETIC_QUERY", "method": "POST", "headers": [["Authorization", "Bearer SYNTHETIC_TOKEN"]], "body": '{"q":"SYNTHETIC_BODY"}'}
    )


@pytest_asyncio.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'requests.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: ComponentRow.__table__.create(conn))
    await upgrade_evaluation_schema(engine)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf.begin() as session:
        session.add(ComponentRow(id="c1", user_id="owner", name="Synthetic", transport="http_post", api_url="https://example.test", validation_type="manual_review"))
    repository = RequestVersionRepository(sf, protection=RequestProtection(Fernet.generate_key()))
    project = await repository.create_project("owner", "Synthetic project")
    component = await repository.link_component("owner", project["id"], ComponentLinkCreate(source_component_id="c1", kind="llm"))
    yield repository, engine, project["id"], component["id"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_append_only_version_has_no_plaintext_values_in_db_or_metadata(repo):
    repository, engine, project, component = repo
    result = await repository.create_request_version("owner", project, component, payload())
    assert result["scope"] == "request_definition_only"
    assert result["request_template"]["method"] == "POST"
    assert result["request_template"]["scope"] == "configuration_only"
    assert len(result["protected_hash"]) == 64
    serialized = json.dumps(result)
    assert "SYNTHETIC" not in serialized and "encrypted_payload" not in serialized
    assert await repository.get_request_version("owner", project, result["id"]) == result
    assert await repository.list_request_versions("owner", project, component) == [result]
    async with engine.connect() as connection:
        stored = (await connection.execute(select(t.request_versions))).mappings().one()
        assert "SYNTHETIC" not in json.dumps(dict(stored))
        assert hashlib.sha256(stored["encrypted_payload"].encode()).hexdigest() == result["protected_hash"]
        events = (await connection.execute(select(t.request_version_audit))).mappings().all()
        assert len(events) == 1 and events[0]["action"] == "request_version_created"
        assert events[0]["request_version_id"] == result["id"]
    frozen = await repository.open_request_version("owner", project, result["id"])
    assert frozen.to_request().to_dict()["url"] == payload().request["url"]
    assert frozen.to_request().body == payload().request["body"]
    assert len(await repository.request_version_audit("owner", project, result["id"])) == 2
    await upgrade_evaluation_schema(engine)
    assert await repository.get_request_version("owner", project, result["id"]) == result


@pytest.mark.asyncio
async def test_owner_and_project_checks_apply_before_protection_or_reference_reads(repo):
    repository, _, project, component = repo
    result = await repository.create_request_version("owner", project, component, payload())
    other_project = await repository.create_project("owner", "Another synthetic project")
    for owner, pid in (("other", project), ("owner", other_project["id"])):
        for operation in (
            repository.get_request_version(owner, pid, result["id"]),
            repository.open_request_version(owner, pid, result["id"]),
            repository.list_request_versions(owner, pid, component),
            repository.create_request_version(owner, pid, component, payload("v2")),
            repository.request_version_audit(owner, pid, result["id"]),
        ):
            with pytest.raises(NotFound):
                await operation
    assert len(await repository.request_version_audit("owner", project, result["id"])) == 1


@pytest.mark.asyncio
async def test_labels_unique_normalized_and_versions_do_not_follow_live_configuration(repo):
    repository, engine, project, component = repo
    first = await repository.create_request_version("owner", project, component, payload(" V1 "))
    with pytest.raises(Conflict):
        await repository.create_request_version("owner", project, component, payload("ｖ１"))
    async with engine.begin() as connection:
        await connection.execute(update(ComponentRow).where(ComponentRow.id == "c1").values(api_url="https://changed.test", api_token="CHANGED_SYNTHETIC_TOKEN"))
    second = await repository.create_request_version("owner", project, component, payload("v2"))
    assert second["protected_hash"] != first["protected_hash"]
    assert (await repository.open_request_version("owner", project, first["id"])).to_request().url == payload().request["url"]
    assert len(await repository.list_request_versions("owner", project, component)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["ciphertext", "hash", "template", "swap"])
async def test_internal_open_rejects_corruption_without_plaintext_or_success_audit(repo, tamper):
    repository, engine, project, component = repo
    first = await repository.create_request_version("owner", project, component, payload())
    second = await repository.create_request_version("owner", project, component, payload("v2"))
    async with engine.begin() as connection:
        if tamper == "ciphertext":
            change = {"encrypted_payload": "SYNTHETIC_INVALID"}
        elif tamper == "hash":
            change = {"protected_hash": "0" * 64}
        elif tamper == "template":
            change = {"request_template": {"schema": "SYNTHETIC_INVALID"}}
        else:
            row = (await connection.execute(select(t.request_versions).where(t.request_versions.c.id == second["id"]))).mappings().one()
            change = {"encrypted_payload": row["encrypted_payload"], "protected_hash": row["protected_hash"]}
        await connection.execute(update(t.request_versions).where(t.request_versions.c.id == first["id"]).values(**change))
    with pytest.raises(RequestProtectionError) as error:
        await repository.open_request_version("owner", project, first["id"])
    assert "SYNTHETIC" not in str(error.value)
    assert len(await repository.request_version_audit("owner", project, first["id"])) == 1


@pytest.mark.asyncio
async def test_migration_adds_only_app_tables_and_preserves_old_data(repo):
    repository, engine, project, component = repo
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE foreign_fixture (value TEXT)"))
        await connection.execute(text("INSERT INTO foreign_fixture VALUES ('synthetic')"))
    before = await repository.list_project_components("owner", project)
    await upgrade_evaluation_schema(engine)
    assert await repository.list_project_components("owner", project) == before
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar() == "eval_0003"
        assert (await connection.execute(text("SELECT value FROM foreign_fixture"))).scalar() == "synthetic"


@pytest.mark.parametrize(
    "change",
    [
        {"confirmed": 1},
        {"confirmed": "true"},
        {"confirmed": False},
        {"version_label": "bad\nlabel"},
        {"request": {"url": "file:///SYNTHETIC"}},
        {"request": {"url": "https://example.test", "headers": [["Host", "SYNTHETIC"]]}},
        {"encrypted_payload": "SYNTHETIC"},
    ],
)
def test_create_contract_is_strict_and_repr_does_not_contain_request_values(change):
    data = payload().model_dump()
    with pytest.raises(ValueError):
        RequestVersionCreate(**{**data, **change})
    assert "SYNTHETIC" not in repr(payload())


@pytest.mark.asyncio
async def test_storage_revalidates_mutated_dto_and_requires_explicit_confirmation(repo):
    repository, _, project, component = repo
    for change in ({"confirmed": False}, {"version_label": "bad\nlabel"}, {"request": {"url": "file:///SYNTHETIC_SECRET"}}):
        changed = payload().model_copy(update=change)
        with pytest.raises(ValueError):
            await repository.create_request_version("owner", project, component, changed)
    assert await repository.list_request_versions("owner", project, component) == []


@pytest.mark.asyncio
async def test_concurrent_same_label_has_one_version_and_one_creation_event(repo):
    import asyncio

    repository, _, project, component = repo
    results = await asyncio.gather(*[repository.create_request_version("owner", project, component, payload()) for _ in range(2)], return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, Conflict) for result in results) == 1
    rows = await repository.list_request_versions("owner", project, component)
    assert len(rows) == 1
    assert len(await repository.request_version_audit("owner", project, rows[0]["id"])) == 1


@pytest.mark.asyncio
async def test_database_rejects_cross_project_request_and_audit_bindings(repo):
    from sqlalchemy.exc import IntegrityError

    repository, engine, project, component = repo
    result = await repository.create_request_version("owner", project, component, payload())
    other = await repository.create_project("owner", "Other synthetic project")
    async with engine.connect() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        await connection.commit()
        row = dict((await connection.execute(select(t.request_versions))).mappings().one())
        await connection.commit()
        with pytest.raises(IntegrityError):
            await connection.execute(insert(t.request_versions).values(**{**row, "id": "forged", "project_id": other["id"], "label_key": "forged"}))
        await connection.rollback()
        with pytest.raises(IntegrityError):
            await connection.execute(insert(t.request_version_audit).values(id="forged", project_id=other["id"], request_version_id=result["id"], actor="owner", action="forged", at="now"))
        await connection.rollback()


@pytest.mark.asyncio
async def test_upgrade_from_eval_0002_preserves_component_inventory(tmp_path, monkeypatch):
    from app.evaluation import schema

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old-requests.db'}")
    original = schema.command.upgrade
    monkeypatch.setattr(schema.command, "upgrade", lambda config, _revision: original(config, "eval_0002"))
    try:
        await upgrade_evaluation_schema(engine)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        repository = RequestVersionRepository(sf, protection=RequestProtection(Fernet.generate_key()))
        project = await repository.create_project("owner", "Synthetic pre-upgrade")
        component = {"id": "linked", "project_id": project["id"], "source_component_id": "c1", "name_at_link": "Synthetic", "kind": "llm", "created_at": "synthetic"}
        async with engine.begin() as connection:
            await connection.execute(insert(t.project_components).values(**component))
        monkeypatch.setattr(schema.command, "upgrade", original)
        await upgrade_evaluation_schema(engine)
        assert await repository.list_project_components("owner", project["id"]) == [component]
        result = await repository.create_request_version("owner", project["id"], "linked", payload())
        assert (await repository.open_request_version("owner", project["id"], result["id"])).to_request().url == payload().request["url"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_crypto_runs_off_the_event_loop_and_read_queries_exclude_ciphertext(repo, monkeypatch):
    import threading

    from sqlalchemy import event

    repository, engine, project, component = repo
    loop_thread = threading.get_ident()
    crypto_threads = []
    seal, open_ = repository.protection.seal, repository.protection.open

    def track_seal(*args):
        crypto_threads.append(threading.get_ident())
        return seal(*args)

    def track_open(*args):
        crypto_threads.append(threading.get_ident())
        return open_(*args)

    monkeypatch.setattr(repository.protection, "seal", track_seal)
    monkeypatch.setattr(repository.protection, "open", track_open)
    result = await repository.create_request_version("owner", project, component, payload())
    await repository.open_request_version("owner", project, result["id"])
    assert len(crypto_threads) == 2 and all(thread != loop_thread for thread in crypto_threads)
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        await repository.get_request_version("owner", project, result["id"])
        await repository.list_request_versions("owner", project, component)
        await repository.request_version_audit("owner", project, result["id"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert statements and all("encrypted_payload" not in statement for statement in statements)


@pytest.mark.asyncio
async def test_metadata_shape_validation_rejects_untrusted_fields(repo):
    repository, engine, project, component = repo
    result = await repository.create_request_version("owner", project, component, payload())
    async with engine.begin() as connection:
        await connection.execute(update(t.request_versions).where(t.request_versions.c.id == result["id"]).values(request_template={"secret": "SYNTHETIC_SECRET"}))
    with pytest.raises(RequestProtectionError):
        await repository.get_request_version("owner", project, result["id"])
    with pytest.raises(RequestProtectionError):
        await repository.list_request_versions("owner", project, component)
    assert len(await repository.request_version_audit("owner", project, result["id"])) == 1
