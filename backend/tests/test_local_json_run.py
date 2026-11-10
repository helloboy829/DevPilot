"""Local run journal: synthetic private paths, fail-closed network and real core."""

import asyncio
import sqlite3
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from uuid import uuid4

import pytest
from devpilot.local_json_run import LocalJournalConflict, LocalJournalUnconfirmed, LocalJSONJournal, LocalRunDefinition, run_local_json_attempts
from devpilot.qa_json_attempt import AttemptObservation
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_run import JSONRunLimits, JSONRunStopped
from devpilot.request_versions import FrozenRequest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


@pytest.fixture(autouse=True)
def close_owned_journals(monkeypatch):
    created = []
    actual = LocalJSONJournal.create.__func__

    def create(cls, *args, **kwargs):
        owned = actual(cls, *args, **kwargs)
        created.append(owned)
        return owned

    monkeypatch.setattr(LocalJSONJournal, "create", classmethod(create))
    yield
    for owned in created:
        owned.close()


def definition(**changes):
    return LocalRunDefinition(**{"run_id": str(uuid4()), "source_sha256": "a" * 64, "input_count": 2, "limits": JSONRunLimits(6, 2, 1000, 61000, 128), "max_total_request_bytes": 4096, "max_total_response_bytes": 774, **changes})


def journal(tmp_path, **changes):
    return LocalJSONJournal.create(tmp_path / "run.sqlite", definition(**changes))


def request():
    return FrozenRequest(url="https://example.test/private", method="POST", headers=(("Authorization", "SYNTHETIC_SECRET"),), body='{"q":""}')


def observation(kind="output_collected", **changes):
    return AttemptObservation(**{"kind": kind, "http_status": 200, "body_bytes": 8, "elapsed_ms": 1.0, "output": "SENSITIVE_OUTPUT", **changes})


@pytest.mark.parametrize(
    "name,value",
    [
        ("run_id", "not-uuid"),
        ("run_id", 1),
        ("source_sha256", "A" * 64),
        ("source_sha256", "secret"),
        ("input_count", True),
        ("input_count", 0),
        ("input_count", 501),
        ("input_count", 7),
        ("max_total_request_bytes", True),
        ("max_total_request_bytes", 0),
        ("max_total_request_bytes", 67108865),
        ("max_total_response_bytes", 128),
        ("max_total_response_bytes", 67108865),
        ("limits", None),
    ],
)
def test_definition_strict_before_file_creation(tmp_path, name, value):
    with pytest.raises(ValueError, match="Invalid local run definition"):
        LocalJSONJournal.create(tmp_path / "run.sqlite", definition(**{name: value}))
    assert list(tmp_path.iterdir()) == []


def test_create_is_exclusive_and_read_cannot_reacquire_capability(tmp_path):
    owned = journal(tmp_path)
    before = (tmp_path / "run.sqlite").read_bytes()
    with pytest.raises(LocalJournalConflict):
        LocalJSONJournal.create(tmp_path / "run.sqlite", definition())
    assert (tmp_path / "run.sqlite").read_bytes() == before
    reader = LocalJSONJournal.open(tmp_path / "run.sqlite")
    assert reader.snapshot() == owned.snapshot()
    assert reader.snapshot().state == "ready"
    for call in (lambda: reader.start(1000), lambda: reader.reserve(1, 10, 1000), lambda: reader.finish(completed=False)):
        with pytest.raises(LocalJournalConflict):
            call()
    assert reader.snapshot().state == "ready"
    with pytest.raises(FrozenInstanceError):
        reader.snapshot().state = "running"


def test_missing_or_invalid_database_fails_without_creating(tmp_path):
    reader = LocalJSONJournal.open(tmp_path / "absent.sqlite")
    with pytest.raises(LocalJournalUnconfirmed):
        reader.snapshot()
    assert list(tmp_path.iterdir()) == []
    (tmp_path / "broken.sqlite").write_bytes(b"not a database")
    with pytest.raises(LocalJournalUnconfirmed):
        LocalJSONJournal.open(tmp_path / "broken.sqlite").snapshot()


def test_sequential_durable_tickets_and_cumulative_non_recycled_budgets(tmp_path):
    owned = journal(tmp_path)
    owned.start(1000)
    for ordinal in range(1, 7):
        ticket = owned.reserve(ordinal, 10, 1000)
        assert ticket.ordinal == ordinal and ticket.sample_index == (ordinal - 1) % 2
        assert "token" not in repr(ticket)
        snapshot = LocalJSONJournal.open(tmp_path / "run.sqlite").snapshot()
        assert snapshot.attempts[-1].state == "dispatched"
        assert snapshot.reserved_response_bytes == ordinal * 129
        owned.record(ticket, observation())
        with pytest.raises(LocalJournalConflict):
            owned.reserve(ordinal, 10, 1000)
        with pytest.raises(LocalJournalConflict):
            owned.record(ticket, observation())
    snapshot = owned.finish(completed=True)
    assert snapshot.state == "collected"
    assert snapshot.reserved_request_bytes == 60 and snapshot.reserved_response_bytes == 774
    assert len(snapshot.attempts) == 6 and all(n.state == "observed" for n in snapshot.attempts)
    with pytest.raises(LocalJournalConflict):
        owned.start(1000)
    with pytest.raises(LocalJournalConflict):
        owned.reserve(7, 10, 1000)


@pytest.mark.parametrize("what", ["ordinal", "concurrency", "request_budget", "response_budget", "deadline", "invalid_bytes"])
def test_admission_guards_cannot_dispatch_or_recycle(tmp_path, what):
    changes = {"max_total_request_bytes": 10} if what == "request_budget" else {"max_total_response_bytes": 129} if what == "response_budget" else {}
    owned = journal(tmp_path, **changes)
    owned.start(1000)
    first = owned.reserve(1, 10, 1000)
    if what in {"request_budget", "response_budget"}:
        owned.record(first, observation())
    if what == "concurrency":
        owned.reserve(2, 10, 1000)
    ordinal = 1 if what == "ordinal" else 3 if what == "concurrency" else 2
    with pytest.raises((LocalJournalConflict, ValueError)):
        owned.reserve(ordinal, True if what == "invalid_bytes" else 10, 61000 if what == "deadline" else 1000)
    snapshot = owned.snapshot()
    assert len(snapshot.attempts) == (2 if what == "concurrency" else 1)
    assert snapshot.reserved_response_bytes == len(snapshot.attempts) * 129


def test_ticket_tampering_and_observation_validation_before_write(tmp_path):
    owned = journal(tmp_path)
    owned.start(1000)
    ticket = owned.reserve(1, 10, 1000)
    for changed in (replace(ticket, token="0" * 64), replace(ticket, sample_index=1), replace(ticket, ordinal=2), replace(ticket, run_id=str(uuid4()))):
        with pytest.raises(LocalJournalConflict):
            owned.record(changed, observation())
    invalid = [
        observation(kind="PASS"),
        observation(http_status=True),
        observation(body_bytes=True),
        observation(elapsed_ms=float("nan")),
        observation(elapsed_ms=-1),
        observation(output=None),
        observation(body_bytes=129),
        observation(kind="http_error"),
        observation(kind="invalid_output", output="hidden"),
    ]
    for value in invalid:
        with pytest.raises(ValueError, match="Invalid local observation"):
            owned.record(ticket, value)
    assert owned.snapshot().attempts[0].state == "dispatched"
    owned.record(ticket, observation())


@pytest.mark.parametrize(
    "kind,status,size", [("output_collected", 200, 8), ("http_error", 503, 0), ("unsupported_response", 200, 0), ("response_limit", 200, 129), ("invalid_output", 200, 8), ("delivery_unknown", None, 129), ("policy_rejected", None, 0)]
)
def test_technical_classifications_never_store_output_or_secrets(tmp_path, kind, status, size):
    owned = journal(tmp_path)
    owned.start(1000)
    ticket = owned.reserve(1, 10, 1000)
    owned.record(ticket, observation(kind=kind, http_status=status, body_bytes=size, output="SENSITIVE_OUTPUT" if kind == "output_collected" else None))
    snapshot = owned.finish(completed=False)
    assert snapshot.state == "interrupted" and snapshot.attempts[0].kind == kind
    data = b"".join(p.read_bytes() for p in tmp_path.iterdir())
    for secret in (b"SENSITIVE_OUTPUT", b"SYNTHETIC_SECRET", b"example.test", b"gold", ticket.token.encode(), owned._token.encode()):
        assert secret not in data
    assert "token" not in repr(snapshot)


def test_unknown_fences_new_dispatch_but_already_sent_can_record(tmp_path):
    owned = journal(tmp_path)
    owned.start(1000)
    first, second = owned.reserve(1, 10, 1000), owned.reserve(2, 10, 1000)
    owned.record(first, observation(kind="delivery_unknown", http_status=None, body_bytes=0, output=None))
    assert not owned.check_active(1000)
    with pytest.raises(LocalJournalConflict):
        owned.reserve(3, 10, 1000)
    owned.record(second, observation())
    snapshot = owned.finish(completed=True)
    assert snapshot.state == "interrupted"
    assert [n.state for n in snapshot.attempts] == ["delivery_unknown", "observed"]


def test_finish_marks_unobserved_dispatch_unknown_and_incomplete_never_collected(tmp_path):
    owned = journal(tmp_path)
    owned.start(1000)
    owned.reserve(1, 10, 1000)
    snapshot = owned.finish(completed=True)
    assert snapshot.state == "interrupted" and snapshot.attempts[0].state == "delivery_unknown"
    assert snapshot.attempts[0].kind == "delivery_unknown"
    assert snapshot.reserved_response_bytes == 129


def test_sqlite_lock_error_is_generic_no_retry_or_state_change(tmp_path):
    owned = journal(tmp_path)
    owned.start(1000)
    connection = sqlite3.connect(tmp_path / "run.sqlite", timeout=0)
    connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(LocalJournalUnconfirmed) as failure:
            owned.reserve(1, 10, 1000)
        assert "sqlite" not in str(failure.value).lower() and str(tmp_path) not in str(failure.value)
    finally:
        connection.rollback()
        connection.close()
    assert owned.snapshot().attempts == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_actual_shared_core_and_collector_durable_before_mock_wire(tmp_path, concurrency, monkeypatch):
    from contextlib import asynccontextmanager

    import httpx
    from devpilot.qa_json_attempt import collect_json_attempt
    from devpilot.qa_json_run import run_json_attempts as actual

    owned = journal(tmp_path, limits=JSONRunLimits(6, concurrency, 1000, 61000, 128))
    delegated, sent, outputs = [], [], []

    async def spy(*args, **kwargs):
        delegated.append(True)
        return await actual(*args, **kwargs)

    monkeypatch.setattr("devpilot.local_json_run.run_json_attempts", spy)

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"a":"SENSITIVE_OUTPUT"}'

    async def wire(spec):
        snapshot = await asyncio.to_thread(LocalJSONJournal.open(tmp_path / "run.sqlite").snapshot)
        assert len(snapshot.attempts) > len(sent)
        assert snapshot.reserved_response_bytes == len(snapshot.attempts) * 129
        sent.append(spec.content)
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=Body())

    @asynccontextmanager
    async def factory(url, *, timeout_seconds):
        async with httpx.AsyncClient(transport=httpx.MockTransport(wire), trust_env=False, follow_redirects=False) as client:
            yield client

    async def collect(spec, binding, limits):
        return await collect_json_attempt(spec, binding, limits, client_factory=factory)

    async def record(ticket, result):
        assert owned.snapshot().attempts[ticket.ordinal - 1].state == "observed"
        outputs.append((ticket.ordinal, result.output))

    async def active():
        return True

    snapshot = await run_local_json_attempts(owned, request(), QAJSONBinding("/q", "/a"), ("first", "second"), now_ms=lambda: 1000, collect_attempt=collect, record_output=record, check_active=active)
    assert delegated == [True] and snapshot.state == "collected"
    assert sent.count(b'{"q":"first"}') == sent.count(b'{"q":"second"}') == 3
    assert sorted(outputs) == [(n, "SENSITIVE_OUTPUT") for n in range(1, 7)]
    with pytest.raises(LocalJournalConflict):
        await run_local_json_attempts(owned, request(), QAJSONBinding("/q", "/a"), ("first", "second"), now_ms=lambda: 1000, collect_attempt=collect, record_output=record, check_active=active)
    assert len(sent) == 6


async def run_synthetic(owned, *, collect=None, record=None, active=None, inputs=("first", "second"), **changes):
    async def default_collect(*args):
        return observation()

    async def default_record(*args):
        pass

    async def default_active():
        return True

    return await run_local_json_attempts(
        owned, request(), QAJSONBinding("/q", "/a"), inputs, **{"now_ms": lambda: 1000, "collect_attempt": collect or default_collect, "record_output": record or default_record, "check_active": active or default_active, **changes}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["unknown", "collector_error", "output_error", "budget"])
async def test_interruption_never_resends_or_finishes_as_collected(tmp_path, reason):
    owned = journal(tmp_path, limits=JSONRunLimits(6, 1, 1000, 61000, 128), **({"max_total_request_bytes": 1} if reason == "budget" else {}))
    sent = []

    async def collect(*args):
        sent.append(1)
        if reason == "collector_error":
            raise RuntimeError("synthetic error")
        return observation(kind="delivery_unknown", http_status=None, body_bytes=0, output=None) if reason == "unknown" else observation()

    async def record(*args):
        if reason == "output_error":
            raise RuntimeError("synthetic output failure")

    with pytest.raises((JSONRunStopped, RuntimeError, LocalJournalConflict)):
        await run_synthetic(owned, collect=collect, record=record)
    snapshot = owned.snapshot()
    assert snapshot.state == "interrupted" and len(sent) <= 1
    assert all(n.state != "dispatched" for n in snapshot.attempts)
    assert len(snapshot.attempts) <= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"now_ms": None}, {"collect_attempt": None}, {"record_output": None}, {"check_active": None}])
async def test_capabilities_required_before_start(tmp_path, changes):
    owned = journal(tmp_path)
    with pytest.raises(ValueError):
        await run_synthetic(owned, **changes)
    assert owned.snapshot().state == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("inputs", [(), [], ("one",), ("one", "two", "three"), (1, "two")])
async def test_all_frozen_inputs_required_before_start(tmp_path, inputs):
    owned = journal(tmp_path)
    with pytest.raises(ValueError):
        await run_synthetic(owned, inputs=inputs)
    assert owned.snapshot().state == "ready"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["reserve", "record", "check_active"])
async def test_repeated_cancellation_drains_original_database_read_or_write_before_finish(tmp_path, monkeypatch, operation):
    owned = journal(tmp_path, limits=JSONRunLimits(6, 1, 1000, 61000, 128))
    entered, release, drained = threading.Event(), threading.Event(), threading.Event()
    real_operation, real_finish = getattr(owned, operation), owned.finish
    events, sent = [], []

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test barrier was not released"
        try:
            return real_operation(*args, **kwargs)
        finally:
            events.append("database drained")
            drained.set()

    def finish(**kwargs):
        assert drained.is_set()
        events.append("finish")
        return real_finish(**kwargs)

    monkeypatch.setattr(owned, operation, blocked)
    monkeypatch.setattr(owned, "finish", finish)

    async def collect(*args):
        sent.append(1)
        if operation == "check_active":
            await asyncio.Event().wait()
        return observation()

    task = asyncio.create_task(run_synthetic(owned, collect=collect))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and not drained.is_set()
        assert owned.snapshot().state == "running"
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert events == ["database drained", "finish"]
    assert owned.snapshot().state == "interrupted"
    if operation == "reserve":
        assert sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_uncertain_dispatch_commit_never_returns_permission_to_collect(tmp_path, monkeypatch, concurrency):
    owned = journal(tmp_path, limits=JSONRunLimits(6, concurrency, 1000, 61000, 128))
    committed = threading.Barrier(concurrency)
    actual, sent = owned.reserve, []

    def uncertain(*args):
        actual(*args)
        committed.wait(timeout=3)
        raise LocalJournalUnconfirmed("Local journal operation unconfirmed")

    monkeypatch.setattr(owned, "reserve", uncertain)

    async def collect(*args):
        sent.append(1)
        return observation()

    with pytest.raises(LocalJournalUnconfirmed):
        await run_synthetic(owned, collect=collect)
    assert sent == []
    snapshot = LocalJSONJournal.open(tmp_path / "run.sqlite").snapshot()
    assert snapshot.state == "interrupted" and len(snapshot.attempts) == concurrency
    assert all(n.state == "delivery_unknown" for n in snapshot.attempts)
    assert snapshot.reserved_response_bytes == 129 * concurrency


def test_real_process_death_retains_dispatch_and_read_only_reopen_cannot_resume(tmp_path):
    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    script = """import os,sys
sys.path.insert(0,sys.argv[1])
from devpilot.local_json_run import LocalJSONJournal,LocalRunDefinition
from devpilot.qa_json_run import JSONRunLimits
j=LocalJSONJournal.create(sys.argv[2],LocalRunDefinition('11111111-1111-4111-8111-111111111111','a'*64,2,JSONRunLimits(6,2,1000,61000,128),4096,774))
j.start(1000);j.reserve(1,10,1000)
os._exit(17)
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(source), str(tmp_path / "run.sqlite")], capture_output=True, text=True, timeout=15)
    assert result.returncode == 17, result.stderr
    reader = LocalJSONJournal.open(tmp_path / "run.sqlite")
    snapshot = reader.snapshot()
    assert snapshot.state == "running" and snapshot.attempts[0].state == "dispatched"
    assert snapshot.reserved_response_bytes == 129
    with pytest.raises(LocalJournalConflict):
        reader.start(62000)
    assert reader.snapshot() == snapshot


def test_source_has_no_business_imports_or_sensitive_persistence():
    import ast

    import devpilot.local_json_run as module

    tree = ast.parse(Path(module.__file__).read_text())
    imported = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported.intersection({"app", "deerflow", "sqlalchemy", "fastapi"})
    assert "run_json_attempts" in Path(module.__file__).read_text()


def test_reordered_render_completion_can_reserve_each_ordinal_once(tmp_path):
    owned = journal(tmp_path)
    owned.start(1000)
    for ordinal in (2, 1, 4, 3, 6, 5):
        ticket = owned.reserve(ordinal, 10, 1000)
        owned.record(ticket, observation())
    assert [n.ordinal for n in owned.finish(completed=True).attempts] == list(range(1, 7))


def test_concurrent_start_has_one_winner_without_retries(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    owned = journal(tmp_path)
    barrier = threading.Barrier(2)

    def start():
        barrier.wait(timeout=3)
        try:
            owned.start(1000)
            return "started"
        except LocalJournalConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: start(), range(2)))
    assert sorted(outcomes) == ["conflict", "started"]
    assert owned.snapshot().state == "running"


def test_real_commit_ack_failure_never_returns_dispatch_ticket(tmp_path, monkeypatch):
    import devpilot.local_json_run as module

    owned = journal(tmp_path)
    owned.start(1000)
    actual = sqlite3.connect
    commits = []

    class Connection:
        def __init__(self, *args, **kwargs):
            self.inner = actual(*args, **kwargs)
            self.inner.row_factory = sqlite3.Row

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self):
            self.inner.commit()
            commits.append(True)
            raise sqlite3.OperationalError("SYNTHETIC_SECRET commit acknowledgement lost")

    monkeypatch.setattr(module.sqlite3, "connect", Connection)
    with pytest.raises(LocalJournalUnconfirmed) as failure:
        owned.reserve(1, 10, 1000)
    assert commits == [True]
    assert "SYNTHETIC_SECRET" not in str(failure.value)
    monkeypatch.setattr(module.sqlite3, "connect", actual)
    snapshot = LocalJSONJournal.open(tmp_path / "run.sqlite").snapshot()
    assert snapshot.attempts[0].state == "dispatched"
    assert snapshot.reserved_response_bytes == 129
    with pytest.raises(LocalJournalConflict):
        owned.reserve(1, 10, 1000)


def test_read_only_snapshot_can_coexist_with_writer_without_db_retries(tmp_path):
    owned = journal(tmp_path)
    owned.start(1000)
    reader = sqlite3.connect(tmp_path / "run.sqlite", isolation_level=None, timeout=0)
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT state FROM local_run").fetchone()[0] == "running"
        ticket = owned.reserve(1, 10, 1000)
        owned.record(ticket, observation())
        assert reader.execute("SELECT count(*) FROM local_attempts").fetchone()[0] == 0
    finally:
        reader.close()
    assert len(owned.snapshot().attempts) == 1


@pytest.mark.asyncio
async def test_active_policy_revocation_drains_collector_and_keeps_cumulative_reservation(tmp_path):
    owned = journal(tmp_path)
    sending = asyncio.Event()
    drained = []

    async def collect(*args):
        sending.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.append(True)

    async def inactive():
        assert sending.is_set()
        return False

    with pytest.raises(JSONRunStopped):
        await run_synthetic(owned, collect=collect, active=inactive)
    assert drained
    snapshot = owned.snapshot()
    assert snapshot.state == "interrupted"
    assert snapshot.reserved_response_bytes == len(snapshot.attempts) * 129
    assert all(n.state == "delivery_unknown" for n in snapshot.attempts)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["start", "finish"])
async def test_start_and_finish_writes_also_drain_repeated_cancellation(tmp_path, monkeypatch, operation):
    owned = journal(tmp_path)
    entered, release, drained = threading.Event(), threading.Event(), threading.Event()
    real = getattr(owned, operation)

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        try:
            return real(*args, **kwargs)
        finally:
            drained.set()

    monkeypatch.setattr(owned, operation, blocked)
    task = asyncio.create_task(run_synthetic(owned))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and not drained.is_set()
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError) and drained.is_set()
    snapshot = owned.snapshot()
    if operation == "start":
        assert snapshot.state == "running" and not snapshot.attempts
    else:
        assert snapshot.state == "collected" and len(snapshot.attempts) == 6
    with pytest.raises(LocalJournalConflict):
        owned.start(1000)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode contract; Windows uses trusted directory ACLs")
def test_new_file_permissions_are_owner_only(tmp_path):
    journal(tmp_path)
    assert (tmp_path / "run.sqlite").stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,status,size", [("http_error", 503, 0), ("unsupported_response", 200, 0), ("response_limit", 200, 129), ("invalid_output", 200, 8), ("policy_rejected", None, 0)])
async def test_all_technical_non_successes_keep_all_frozen_ordinals_not_pass(tmp_path, kind, status, size):
    owned = journal(tmp_path)
    recorded = []

    async def collect(*args):
        return observation(kind=kind, http_status=status, body_bytes=size, output=None)

    async def record(ticket, result):
        recorded.append(ticket.ordinal)

    snapshot = await run_synthetic(owned, collect=collect, record=record)
    assert snapshot.state == "collected" and snapshot.scope == "external_unverified_technical_only"
    assert sorted(recorded) == [1, 2, 3, 4, 5, 6]
    assert len(snapshot.attempts) == snapshot.definition.limits.request_count
    assert all(n.kind == kind for n in snapshot.attempts)
    assert snapshot.reserved_response_bytes == 774
    assert not hasattr(snapshot, "passed") and not hasattr(snapshot, "approved")


@pytest.mark.asyncio
async def test_finalization_failure_is_retained_as_cause_not_hidden(tmp_path, monkeypatch):
    owned = journal(tmp_path)

    def fail_finish(**kwargs):
        raise LocalJournalUnconfirmed("Local journal operation unconfirmed")

    monkeypatch.setattr(owned, "finish", fail_finish)

    async def collect(*args):
        raise RuntimeError("synthetic collector failure")

    with pytest.raises(RuntimeError) as error:
        await run_synthetic(owned, collect=collect)
    assert isinstance(error.value.__cause__, LocalJournalUnconfirmed)
    assert owned.snapshot().state == "running"
    assert all(n.state == "dispatched" for n in owned.snapshot().attempts)


@pytest.mark.asyncio
async def test_actual_source_isolated_complete_mock_run_without_business_imports(tmp_path):
    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    script = """import asyncio,importlib.abc,socket,sys
sys.path.insert(0,sys.argv[1])
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi','openpyxl'}:raise AssertionError('business import')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs):raise AssertionError('real network')
socket.getaddrinfo=denied;socket.socket.connect=denied;socket.socket.connect_ex=denied;socket.socket.sendto=denied
from contextlib import asynccontextmanager
import httpx
from devpilot.local_json_run import LocalJSONJournal,LocalRunDefinition,run_local_json_attempts
from devpilot.qa_json_attempt import collect_json_attempt
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_run import JSONRunLimits
from devpilot.request_versions import FrozenRequest
class Body(httpx.AsyncByteStream):
 async def __aiter__(self):yield b'{"a":"synthetic"}'
 async def aclose(self):pass
async def main():
 j=LocalJSONJournal.create(sys.argv[2],LocalRunDefinition('11111111-1111-4111-8111-111111111111','a'*64,2,JSONRunLimits(5,2,1000,61000,128),4096,645))
 sent=[];outputs=[]
 async def wire(request):
  s=await asyncio.to_thread(j.snapshot)
  assert len(s.attempts)>len(sent)
  sent.append(request.content)
  return httpx.Response(200,headers={'content-type':'application/json'},stream=Body())
 @asynccontextmanager
 async def factory(url,*,timeout_seconds):
  async with httpx.AsyncClient(transport=httpx.MockTransport(wire),trust_env=False,follow_redirects=False) as client:yield client
 async def collect(spec,binding,limits):return await collect_json_attempt(spec,binding,limits,client_factory=factory)
 async def record(ticket,result):outputs.append((ticket.ordinal,result.output))
 async def active():return True
 s=await run_local_json_attempts(j,FrozenRequest('https://example.test/qa','POST',(),'{"q":""}'),QAJSONBinding('/q','/a'),('first','second'),now_ms=lambda:1000,collect_attempt=collect,record_output=record,check_active=active)
 assert s.state=='collected' and len(s.attempts)==5 and s.reserved_response_bytes==645
 assert sorted(outputs)==[(n,'synthetic') for n in range(1,6)]
 assert sent.count(b'{"q":"first"}')==3 and sent.count(b'{"q":"second"}')==2
 reader=LocalJSONJournal.open(sys.argv[2]);assert reader.snapshot()==s
 print('local-qa-json-journal.v1')
asyncio.run(main())
"""
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", "-c", script, str(source), str(tmp_path / "run.sqlite")], capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "local-qa-json-journal.v1"


@pytest.mark.parametrize("now", [0, False, 1.0, "1000", 9007199254740992])
def test_invalid_clock_rejected_before_state_changes(tmp_path, now):
    owned = journal(tmp_path)
    with pytest.raises(ValueError, match="Invalid local clock"):
        owned.start(now)
    assert owned.snapshot().state == "ready"


def test_unrecognized_schema_fails_closed_and_does_not_migrate(tmp_path):
    journal(tmp_path)
    connection = sqlite3.connect(tmp_path / "run.sqlite")
    connection.execute("UPDATE local_run SET schema='unknown'")
    connection.commit()
    connection.close()
    before = (tmp_path / "run.sqlite").read_bytes()
    with pytest.raises(LocalJournalUnconfirmed):
        LocalJSONJournal.open(tmp_path / "run.sqlite").snapshot()
    assert (tmp_path / "run.sqlite").read_bytes() == before


def test_context_close_revokes_capability_and_releases_idle_anchor(tmp_path):
    with journal(tmp_path) as owned:
        assert owned._anchor is not None and not owned._anchor.in_transaction
        owned.start(1000)
        assert not owned._anchor.in_transaction
    assert owned._anchor is None
    with pytest.raises(LocalJournalConflict):
        owned.reserve(1, 10, 1000)
    assert owned.snapshot().state == "running"


def test_concurrent_read_reconciliation_and_writes_keep_idle_wal_anchor(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    owned = journal(tmp_path, limits=JSONRunLimits(100, 2, 1000, 61000, 128), max_total_response_bytes=12900)
    barrier = threading.Barrier(2)

    def reads():
        barrier.wait(timeout=3)
        for _ in range(100):
            snapshot = LocalJSONJournal.open(tmp_path / "run.sqlite").snapshot()
            assert snapshot.reserved_response_bytes == len(snapshot.attempts) * 129
        return True

    owned.start(1000)
    with ThreadPoolExecutor(max_workers=1) as pool:
        reader = pool.submit(reads)
        barrier.wait(timeout=3)
        for ordinal in range(1, 101):
            owned.record(owned.reserve(ordinal, 10, 1000), observation())
        assert reader.result(timeout=5)
    assert owned._anchor is not None and not owned._anchor.in_transaction
    assert owned.finish(completed=True).state == "collected"


def test_same_path_reconciliation_handles_share_owner_lock_and_aliases(tmp_path):
    owned = journal(tmp_path)
    opened = LocalJSONJournal.open(tmp_path / "run.sqlite")
    aliased = LocalJSONJournal.open(tmp_path / "unused" / ".." / "run.sqlite")
    unrelated = LocalJSONJournal.open(tmp_path / "different.sqlite")
    assert opened._lock is owned._lock and aliased._lock is owned._lock
    assert unrelated._lock is not owned._lock


def test_readonly_reconciliation_waits_for_same_process_writer_lock_without_sqlite_retry(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    import devpilot.local_json_run as module

    owned = journal(tmp_path)
    reader = LocalJSONJournal.open(tmp_path / "run.sqlite")
    started, connected = threading.Event(), threading.Event()
    real_connect = module.sqlite3.connect

    def connect(*args, **kwargs):
        connected.set()
        return real_connect(*args, **kwargs)

    def read():
        started.set()
        return reader.snapshot()

    monkeypatch.setattr(module.sqlite3, "connect", connect)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with owned._lock:
            future = pool.submit(read)
            assert started.wait(3)
            assert not connected.is_set() and not future.done()
        assert future.result(3).state == "ready" and connected.is_set()


def test_process_path_lock_registry_does_not_retain_inactive_handles(tmp_path):
    import weakref

    opened = LocalJSONJournal.open(tmp_path / "not_created.sqlite")
    reference = weakref.ref(opened._lock)
    del opened
    assert reference() is None
