"""Synthetic SQLite upgrade/backup recovery; never open an operator database."""

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_dispatch_journal import prepared as prepared
from test_qa_evidence import captured as captured
from test_qa_report_archives import archives, payload
from test_qa_retests import pair, request, store

from app.evaluation import schema
from app.evaluation.qa_reports import ReportArchiveRepository
from app.evaluation.qa_retests import RetestRepository
from app.evaluation.report_docx import render_archived_docx
from app.gateway.auth.password import hash_password_async, verify_password_async
from deerflow.persistence.bootstrap import _get_head_revision, bootstrap_schema
from deerflow.persistence.user.model import UserRow

pytestmark = [pytest.mark.asyncio, pytest.mark.parametrize("prepared", ["eval_0009"], indirect=True)]
REVISIONS = ("eval_0010", "eval_0011", "eval_0012", "eval_0013", "eval_0014")
ADDITIONS = (
    {"evaluation_review_tasks", "evaluation_review_task_assignments", "evaluation_review_task_decisions", "evaluation_review_task_resolutions", "evaluation_review_task_audit"},
    {"evaluation_run_assessments"},
    {"evaluation_independent_report_archives", "evaluation_independent_retest_archives"},
    {"evaluation_authorized_exports", "evaluation_export_audit"},
    {"evaluation_external_qa_intakes", "evaluation_external_qa_intake_audit"},
)
PASSWORD = "SYNTHETIC_RECOVERY_PASSWORD_ONLY"


def config(url):
    value = Config()
    value.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
    value.attributes.update(engine_url=url, postgres_schema="")
    return value


def upgrade(url, revision):
    with schema._MIGRATION_LOCK:
        command.upgrade(config(url), revision)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def snapshot(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        definitions = connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema WHERE sql IS NOT NULL ORDER BY type, name").fetchall()
        tables = {}
        for (name,) in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name"):
            rows = connection.execute("SELECT * FROM " + quote(name)).fetchall()
            # Hash every value, including ciphertext/blobs and empty table membership.
            encoded = [[{"bytes_hex": value.hex()} if isinstance(value, bytes) else value for value in row] for row in rows]
            tables[name] = sorted(json.dumps(row, ensure_ascii=True, separators=(",", ":")) for row in encoded)
        return {"definitions": definitions, "tables": tables}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def backup(source, destination):
    # These are fresh test-owned paths only. A stale destination is never replaced.
    with destination.open("xb"):
        pass
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original, closing(sqlite3.connect(destination)) as copied:
        original.backup(copied)
    with destination.open("rb") as descriptor:
        os.fsync(descriptor.fileno())


def unchanged(before, after, revision):
    assert before["tables"].keys() <= after["tables"].keys()
    for name, rows in before["tables"].items():
        expected = [json.dumps([revision], separators=(",", ":"))] if name == "devpilot_alembic_version" else rows
        assert after["tables"][name] == expected, "Historical table changed: " + name
    old_names = before["tables"].keys()
    assert [row for row in after["definitions"] if row[2] in old_names] == before["definitions"]


@dataclass
class RecoverySource:
    path: Path
    repo: object
    project: str
    first: dict
    second: dict
    report: dict
    retest: dict
    original: dict


@pytest_asyncio.fixture
async def recovery(captured, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Synthetic SQLite recovery must not use DNS or sockets")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)
    repo, engine, project, _, _, _, _ = captured
    # Real Harness bootstrap creates its actual tables and real revision ledger.
    # The existing fixture's App database is pinned to deployed eval_0009.
    await bootstrap_schema(engine, backend="sqlite")
    path = Path(engine.url.database).resolve()
    anchor = await asyncio.to_thread(sqlite3.connect, path, check_same_thread=False, isolation_level=None)
    try:
        assert (await asyncio.to_thread(lambda: anchor.execute("PRAGMA journal_mode=WAL").fetchone())) == ("wal",)
        await asyncio.to_thread(anchor.execute, "PRAGMA wal_autocheckpoint=0")
        password_hash = await hash_password_async(PASSWORD)
        async with repo.sf.begin() as session:
            for ordinal, role in enumerate(("admin", "user", "user")):
                session.add(UserRow(id=str(UUID(int=100 + ordinal)), email=f"synthetic-recovery-{ordinal}@example.invalid", password_hash=password_hash, system_role=role, token_version=10 + ordinal, needs_setup=ordinal == 2))
        first, second = await pair(captured)
        report = await archives(repo).create_archive("owner", project, uuid4().hex, payload(first))
        retest = await store(repo).create_retest("owner", project, uuid4().hex, request(first, second))
        await asyncio.to_thread(anchor.execute, "PRAGMA wal_checkpoint(TRUNCATE)")
        # A real committed account change exists only in WAL, with an idle anchor.
        await asyncio.to_thread(anchor.execute, "UPDATE users SET token_version=19 WHERE id=?", (str(UUID(int=100)),))
        assert Path(str(path) + "-wal").stat().st_size > 32
        original = await asyncio.to_thread(snapshot, path)
        assert original["tables"]["alembic_version"] == [json.dumps([_get_head_revision()], separators=(",", ":"))]
        assert original["tables"]["devpilot_alembic_version"] == ['["eval_0009"]']
        yield RecoverySource(path, repo, project, first, second, report, retest, original)
    finally:
        await asyncio.to_thread(anchor.close)


async def verify_reads(source, path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(path))

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    sf = async_sessionmaker(engine, expire_on_commit=False)
    options = {"protection": source.repo.protection, "evidence_protection": source.repo.evidence_protection, "clock_ms": source.repo.clock_ms}
    reports = ReportArchiveRepository(sf, **options)
    retests = RetestRepository(sf, **options)
    try:
        assert await reports.get_archive("owner", source.project, source.report["id"]) == source.report
        assert await retests.get_retest("owner", source.project, source.retest["id"]) == source.retest
        assert render_archived_docx(await reports.get_archive("owner", source.project, source.report["id"])) == render_archived_docx(source.report)
        for summary in (source.first, source.second):
            assert await reports.get_summary("owner", source.project, summary["run_id"]) == summary
            assert summary["human_pass_rate"]["denominator"] == 2
            for ordinal in (1, 2):
                case = await reports.open_case("owner", source.project, summary["run_id"], ordinal)
                assert case["output"] == "SYNTHETIC_OUTPUT" and case["expected"] == "SYNTHETIC_GOLD"
                assert case["reviews"][0]["note"] == "SYNTHETIC_REVIEW_NOTE"
        async with sf() as session:
            for ordinal, role in enumerate(("admin", "user", "user")):
                user = await session.get(UserRow, str(UUID(int=100 + ordinal)))
                assert user.system_role == role and user.needs_setup is (ordinal == 2)
                assert user.token_version == (19 if ordinal == 0 else 10 + ordinal)
                assert await verify_password_async(PASSWORD, user.password_hash)
    finally:
        await engine.dispose()


async def restore_and_verify(source, saved, restored):
    await asyncio.to_thread(backup, saved, restored)
    assert await asyncio.to_thread(snapshot, restored) == source.original
    await verify_reads(source, restored)


@pytest.mark.parametrize("mode", ["stepwise", "head"])
async def test_wal_backup_upgrade_and_independent_old_version_restore(recovery, tmp_path, mode):
    source = recovery
    saved, candidate = tmp_path / "before-upgrade.db", tmp_path / "candidate.db"
    await asyncio.to_thread(backup, source.path, saved)
    assert await asyncio.to_thread(snapshot, saved) == source.original
    saved_hash = hashlib.sha256(saved.read_bytes()).hexdigest()
    await asyncio.to_thread(backup, source.path, candidate)
    url = make_url("sqlite+aiosqlite:///" + str(candidate))
    versions = REVISIONS if mode == "stepwise" else ("head",)
    expected_names = set(source.original["tables"])
    stages = []
    for target in versions:
        await asyncio.to_thread(upgrade, url, target)
        actual = await asyncio.to_thread(snapshot, candidate)
        revision = "eval_0014" if target == "head" else target
        expected_names.update(set.union(*ADDITIONS) if target == "head" else ADDITIONS[REVISIONS.index(target)])
        assert set(actual["tables"]) == expected_names
        unchanged(source.original, actual, revision)
        stages.append({"revision": revision, "tables": len(actual["tables"]), "all_historical_tables_unchanged": True})
    await asyncio.to_thread(upgrade, url, "head")
    unchanged(source.original, await asyncio.to_thread(snapshot, candidate), "eval_0014")
    await verify_reads(source, candidate)

    def candidate_write():
        with closing(sqlite3.connect(candidate)) as connection:
            connection.execute("UPDATE users SET token_version=99 WHERE id=?", (str(UUID(int=100)),))
            connection.commit()

    await asyncio.to_thread(candidate_write)
    assert (await asyncio.to_thread(snapshot, candidate))["tables"]["users"] != source.original["tables"]["users"]
    assert await asyncio.to_thread(snapshot, source.path) == source.original
    await restore_and_verify(source, saved, tmp_path / "restored-old-version.db")
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == saved_hash
    print(
        json.dumps(
            {
                "schema": "synthetic-qa-upgrade-recovery.v1",
                "mode": mode,
                "from": "eval_0009",
                "to": "eval_0014",
                "all_historical_tables": len(source.original["tables"]),
                "stages": stages,
                "snapshot_sha256": digest(source.original),
                "backup_sha256": saved_hash,
                "wal_committed_account_restored": True,
                "all_frozen_samples_per_run": 2,
                "report_retest_word_unchanged": True,
                "old_version_restored_to_fresh_path": True,
                "post_backup_candidate_write_is_not_restored": True,
                "business_database_opened": False,
                "approval_granted": False,
            },
            sort_keys=True,
        )
    )


async def test_main_file_copy_loses_committed_wal_account_change(recovery, tmp_path):
    copied = tmp_path / "unsafe-main-only.db"
    await asyncio.to_thread(shutil.copyfile, recovery.path, copied)
    unsafe = await asyncio.to_thread(snapshot, copied)
    assert unsafe["tables"]["users"] != recovery.original["tables"]["users"]
    with pytest.raises(AssertionError, match="Historical table changed: users"):
        unchanged(recovery.original, unsafe, "eval_0009")


async def test_mid_chain_failure_restores_verified_backup_without_downgrade(recovery, tmp_path, monkeypatch):
    saved, candidate = tmp_path / "before-failure.db", tmp_path / "failed-candidate.db"
    await asyncio.to_thread(backup, recovery.path, saved)
    await asyncio.to_thread(backup, recovery.path, candidate)
    url = make_url("sqlite+aiosqlite:///" + str(candidate))
    await asyncio.to_thread(upgrade, url, "eval_0010")
    real_upgrade = schema.command.upgrade

    def fail_after_committed_revision(value, revision):
        real_upgrade(value, "eval_0011")
        raise RuntimeError("SYNTHETIC_LOST_MIGRATION_COMPLETION")

    with monkeypatch.context() as patch:
        patch.setattr(schema.command, "upgrade", fail_after_committed_revision)
        with pytest.raises(RuntimeError, match="SYNTHETIC_LOST_MIGRATION_COMPLETION"):
            await asyncio.to_thread(upgrade, url, "head")
    assert (await asyncio.to_thread(snapshot, candidate))["tables"]["devpilot_alembic_version"] == ['["eval_0011"]']
    # Do not repair/retry the failed candidate or run a destructive downgrade.
    failed = await asyncio.to_thread(snapshot, candidate)
    await restore_and_verify(recovery, saved, tmp_path / "restored-after-failure.db")
    assert await asyncio.to_thread(snapshot, candidate) == failed
    assert await asyncio.to_thread(snapshot, recovery.path) == recovery.original


async def test_all_table_verifier_rejects_historical_row_loss(recovery, tmp_path):
    for table in ("users", "component_tests", "evaluation_datasets", "evaluation_output_evidence", "evaluation_report_archives", "evaluation_retest_archives", "alembic_version"):
        candidate = tmp_path / (table + ".db")
        await asyncio.to_thread(backup, recovery.path, candidate)

        def remove():
            with closing(sqlite3.connect(candidate)) as connection:
                assert connection.execute("SELECT COUNT(*) FROM " + quote(table)).fetchone()[0] > 0
                connection.execute("DELETE FROM " + quote(table))
                connection.commit()

        await asyncio.to_thread(remove)
        with pytest.raises(AssertionError):
            unchanged(recovery.original, await asyncio.to_thread(snapshot, candidate), "eval_0009")
        assert await asyncio.to_thread(snapshot, recovery.path) == recovery.original


async def test_backup_never_overwrites_existing_recovery_artifact(recovery, tmp_path):
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"SYNTHETIC_EXISTING_RECOVERY_ARTIFACT")
    with pytest.raises(FileExistsError):
        await asyncio.to_thread(backup, recovery.path, destination)
    assert destination.read_bytes() == b"SYNTHETIC_EXISTING_RECOVERY_ARTIFACT"
    assert await asyncio.to_thread(snapshot, recovery.path) == recovery.original


async def test_verifier_rejects_empty_table_loss_and_legacy_schema_changes(recovery, tmp_path):
    for damage in ("drop-empty-table", "add-column"):
        candidate = tmp_path / (damage + ".db")
        await asyncio.to_thread(backup, recovery.path, candidate)

        def change_schema():
            with closing(sqlite3.connect(candidate)) as connection:
                if damage == "drop-empty-table":
                    assert connection.execute("SELECT COUNT(*) FROM feedback").fetchone() == (0,)
                    connection.execute("DROP TABLE feedback")
                else:
                    connection.execute("ALTER TABLE users ADD COLUMN synthetic_unexpected TEXT")
                connection.commit()

        await asyncio.to_thread(change_schema)
        with pytest.raises(AssertionError):
            unchanged(recovery.original, await asyncio.to_thread(snapshot, candidate), "eval_0009")
        assert await asyncio.to_thread(snapshot, recovery.path) == recovery.original


async def test_exact_candidate_migration_chain_is_pinned(recovery):
    scripts = ScriptDirectory.from_config(config(make_url("sqlite+aiosqlite:///" + str(recovery.path))))
    assert tuple(reversed([item.revision for item in scripts.iterate_revisions("head", "eval_0009")])) == REVISIONS
