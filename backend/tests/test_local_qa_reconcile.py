"""Trusted local journal reconciliation; real SQLite, no network or evidence opens."""

import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from devpilot import local_qa_reconcile as module
from devpilot.local_json_run import LocalJSONJournal, LocalRunDefinition
from devpilot.qa_json_attempt import AttemptObservation
from devpilot.qa_json_run import JSONRunLimits


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket

    def deny(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", deny)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, deny)


@pytest.fixture
def owned(tmp_path):
    definition = LocalRunDefinition(str(uuid4()), "a" * 64, 2, JSONRunLimits(4, 2, 500, 100000, 64), 4096, 260)
    journal = LocalJSONJournal.create(tmp_path / "journal.sqlite", definition)
    yield journal
    journal.close()


def run_id(owned):
    return owned.snapshot().definition.run_id


def read(owned):
    return module.reconcile(owned._path, run_id(owned))


def observation(kind="output_collected", **changes):
    return AttemptObservation(**{"kind": kind, "http_status": 200, "body_bytes": 8, "elapsed_ms": 1.0, "output": "PRIVATE_OUTPUT", **changes})


def observe_all(owned):
    owned.start(1000)
    for ordinal in range(1, 5):
        owned.record(owned.reserve(ordinal, ordinal * 10, 1000), observation())
    return owned.finish(completed=True)


def test_ready_keeps_all_frozen_denominators_and_does_not_open_outputs(owned, monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No sensitive file reads")

    monkeypatch.setattr(Path, "read_bytes", deny)
    monkeypatch.setattr(Path, "read_text", deny)
    result = read(owned)
    assert result["schema"] == "local-qa-reconciliation.v1"
    assert result["state"] == "ready"
    assert result["scope"] == "external_unverified_technical_only"
    assert result["verdict"] == "NOT_EVALUATED"
    assert result["frozen_input_count"] == 2 and result["frozen_request_count"] == 4
    assert result["reserved_attempt_count"] == result["covered_input_count"] == 0
    assert result["unreserved_in_snapshot_count"] == 4
    for name in ("resend_permitted", "resume_permitted", "platform_provenance_verified", "output_content_verified"):
        assert result[name] is False
    assert result["declared_source_sha256"] == "a" * 64
    assert "claim" not in json.dumps(result) and "output" not in result


def test_live_snapshot_has_no_write_sql_or_claim_and_owner_can_continue(owned, monkeypatch):
    owned.start(1000)
    ticket = owned.reserve(1, 10, 1000)
    actual = sqlite3.connect
    calls, sql = [], []

    def connect(*args, **kwargs):
        calls.append((args, kwargs))
        db = actual(*args, **kwargs)
        db.set_trace_callback(sql.append)
        return db

    monkeypatch.setattr(sqlite3, "connect", connect)
    result = read(owned)
    assert result["state"] == "running"
    assert result["attempt_states"] == {"dispatched": 1, "observed": 0, "delivery_unknown": 0}
    assert result["reserved_response_bytes"] == 65
    assert result["unreserved_in_snapshot_count"] == 3
    assert all("mode=ro" in args[0] for args, _ in calls)
    assert all(statement.split()[0].upper() in {"PRAGMA", "BEGIN", "SELECT", "COMMIT"} for statement in sql)
    monkeypatch.setattr(sqlite3, "connect", actual)
    owned.record(ticket, observation())
    assert owned.reserve(2, 20, 1000).ordinal == 2  # Reader did not revoke owner.


def test_collected_is_only_technical_and_does_not_certify_output_fsync(owned, tmp_path):
    observe_all(owned)
    owned.close()
    before = owned._path.read_bytes()
    (tmp_path / "observations.jsonl").write_text("SENSITIVE broken/truncated output", encoding="utf-8")
    result = read(owned)
    assert result["state"] == "collected" and result["verdict"] == "NOT_EVALUATED"
    assert result["attempt_states"]["observed"] == result["frozen_request_count"] == 4
    assert result["observation_kinds"]["output_collected"] == 4
    assert result["reserved_request_bytes"] == 100 and result["reserved_response_bytes"] == 260
    assert result["covered_input_count"] == 2
    assert not result["output_content_verified"] and not result["resend_permitted"]
    assert owned._path.read_bytes() == before
    assert "SENSITIVE" not in json.dumps(result)


def test_interrupted_without_observation_remains_unknown(owned):
    owned.start(1000)
    owned.reserve(1, 10, 1000)
    owned.finish(completed=False)
    result = read(owned)
    assert result["state"] == "interrupted"
    assert result["attempt_states"]["delivery_unknown"] == 1
    assert result["observation_kinds"]["delivery_unknown"] == 1
    assert result["frozen_request_count"] == 4 and result["unreserved_in_snapshot_count"] == 3
    assert not result["resend_permitted"]


@pytest.mark.parametrize("kind,status,size", [("http_error", 503, 0), ("unsupported_response", 200, 0), ("response_limit", 200, 65), ("invalid_output", 200, 8), ("policy_rejected", None, 0), ("delivery_unknown", None, 0)])
def test_all_failure_kinds_are_metadata_not_pass(owned, kind, status, size):
    owned.start(1000)
    owned.record(owned.reserve(1, 10, 1000), observation(kind, http_status=status, body_bytes=size, output=None))
    owned.finish(completed=False)
    result = read(owned)
    assert result["observation_kinds"][kind] == 1
    assert result["observation_kinds"]["output_collected"] == 0
    assert result["verdict"] == "NOT_EVALUATED" and result["frozen_request_count"] == 4
    assert result["reserved_response_bytes"] == 65


def test_partial_interrupted_snapshot_can_still_have_inflight_ordinals(owned):
    owned.start(1000)
    owned.record(owned.reserve(1, 10, 1000), observation("delivery_unknown", http_status=None, body_bytes=0, output=None))
    # An interrupted run may still have another earlier-dispatched attempt draining.
    with sqlite3.connect(owned._path) as db:
        db.execute("INSERT INTO local_attempts VALUES (2, 1, 20, 'synthetic', 'dispatched', NULL, NULL, NULL, NULL)")
        db.execute("UPDATE local_run SET request_bytes=30, response_bytes=130")
    result = read(owned)
    assert result["attempt_states"] == {"dispatched": 1, "observed": 0, "delivery_unknown": 1}
    assert result["unreserved_in_snapshot_count"] == 2 and not result["resume_permitted"]


@pytest.mark.parametrize("bad_id", [None, 123, "", "../private", "00000000-0000-0000-0000-000000000000", "PRIVATE_ID"])
def test_requires_exact_canonical_original_id_before_returning_metadata(owned, bad_id):
    with pytest.raises(ValueError, match="^Local QA reconciliation unconfirmed; never retry or resend$"):
        module.reconcile(owned._path, bad_id)


def test_uppercase_uuid_is_not_silently_normalized(owned):
    with pytest.raises(ValueError):
        module.reconcile(owned._path, run_id(owned).upper())


def test_missing_or_invalid_file_never_created_or_repaired(tmp_path):
    path = tmp_path / "absent.sqlite"
    for data in (None, b"not SQLite", b""):
        if data is not None:
            path.write_bytes(data)
        with pytest.raises(ValueError):
            module.reconcile(path, str(uuid4()))
        assert path.exists() is (data is not None)
        if data is not None:
            assert path.read_bytes() == data


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_rejects_nonregular_or_oversized_files(owned, suffix):
    owned.close()
    path = Path(str(owned._path) + suffix)
    with path.open("wb") as stream:
        stream.truncate(module._MAX_FILE_BYTES + 1)
    with pytest.raises(ValueError):
        module.reconcile(owned._path, "00000000-0000-0000-0000-000000000000")


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO and symlink contract")
@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
@pytest.mark.parametrize("kind", ["link", "fifo", "directory"])
def test_no_links_fifos_or_directories(owned, tmp_path, suffix, kind):
    ident = run_id(owned)
    owned.close()
    path = Path(str(owned._path) + suffix)
    if path.exists():
        path.unlink()
    if kind == "link":
        path.symlink_to(tmp_path / "absent-target")
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    with pytest.raises(ValueError):
        module.reconcile(owned._path, ident)
    assert path.is_symlink() if kind == "link" else path.exists()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE local_run SET state='PASS'",
        "UPDATE local_run SET state='collected'",
        "UPDATE local_run SET state='ready'",
        "UPDATE local_run SET request_bytes=-1",
        "UPDATE local_run SET request_bytes=request_bytes+1",
        "UPDATE local_run SET response_bytes=response_bytes-1",
        "UPDATE local_attempts SET ordinal=5",
        "UPDATE local_attempts SET sample_index=1",
        "UPDATE local_attempts SET request_bytes=0",
        "UPDATE local_attempts SET state='PASS'",
        "UPDATE local_attempts SET state='dispatched'",
        "UPDATE local_attempts SET kind='private-injected-value'",
        "UPDATE local_attempts SET state='delivery_unknown'",
        "UPDATE local_attempts SET http_status=503",
        "UPDATE local_attempts SET response_bytes=0",
        "UPDATE local_attempts SET response_bytes=65",
        "UPDATE local_attempts SET elapsed_ms=-1",
        "UPDATE local_attempts SET elapsed_ms=NULL",
    ],
)
def test_incoherent_database_never_produces_receipt(owned, sql):
    owned.start(1000)
    owned.record(owned.reserve(1, 10, 1000), observation())
    ident = run_id(owned)
    owned.close()
    with sqlite3.connect(owned._path) as db:
        db.execute(sql)
    with pytest.raises(ValueError):
        module.reconcile(owned._path, ident)


@pytest.mark.parametrize("changes", [{"state": "running"}, {"state": "collected"}])
def test_unknown_cannot_be_reported_running_or_collected(owned, changes):
    owned.start(1000)
    owned.reserve(1, 10, 1000)
    snapshot = owned.finish(completed=False)
    with pytest.raises(ValueError):
        module._validate(replace(snapshot, **changes), snapshot.definition.run_id)


def test_single_read_no_retries_and_close_on_validation_failure(owned, monkeypatch):
    seen = []
    actual_open = LocalJSONJournal.open.__func__

    def opening(cls, path):
        reader = actual_open(cls, path)
        actual_close = reader.close

        def close():
            seen.append("close")
            actual_close()

        reader.close = close
        actual_snapshot = reader.snapshot

        def snapshot():
            seen.append("snapshot")
            return actual_snapshot()

        reader.snapshot = snapshot
        return reader

    monkeypatch.setattr(LocalJSONJournal, "open", classmethod(opening))
    with pytest.raises(ValueError):
        module.reconcile(owned._path, str(uuid4()))
    assert seen == ["snapshot", "close"]


def test_database_lock_fails_without_retry_or_timeout_increase(owned):
    ident = run_id(owned)
    owned.close()
    with sqlite3.connect(owned._path) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("BEGIN EXCLUSIVE")
        with pytest.raises(ValueError):
            module.reconcile(owned._path, ident)
        db.rollback()


def test_main_metadata_only_and_invalid_arguments_are_generic(owned, capsys):
    code = module.main(["--journal", str(owned._path), "--run-id", run_id(owned)])
    output = capsys.readouterr()
    assert code == 0 and not output.err
    assert json.loads(output.out)["state"] == "ready"
    assert module.main(["--journal", "PRIVATE_PATH", "--run-id", "PRIVATE_ID", "--execute"]) == 1
    output = capsys.readouterr()
    assert not output.out and "PRIVATE" not in output.err and "Traceback" not in output.err
    assert "never resend" in output.err


def test_keyboard_interrupt_is_not_a_receipt(owned, monkeypatch, capsys):
    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "reconcile", interrupt)
    assert module.main(["--journal", str(owned._path), "--run-id", run_id(owned)]) == 130
    output = capsys.readouterr()
    assert not output.out and "never resend" in output.err


_ISOLATED_RECONCILE = r"""
import importlib.abc,json,runpy,socket,sys
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in {'app','deerflow','langchain','langgraph'}:
   raise AssertionError('business import forbidden')
sys.meta_path.insert(0,Fence())
def deny(*args,**kwargs):raise AssertionError('real network forbidden')
socket.getaddrinfo=deny
for name in ('connect','connect_ex','sendto'):setattr(socket.socket,name,deny)
sys.path.insert(0,sys.argv[1])
sys.argv=['devpilot.local_qa_reconcile','--journal',sys.argv[2],'--run-id',sys.argv[3]]
runpy.run_module('devpilot.local_qa_reconcile',run_name='__main__')
"""


def test_actual_isolated_module_entry_without_business_or_wire(owned):
    observe_all(owned)
    owned.close()
    result = subprocess.run([sys.executable, "-I", "-c", _ISOLATED_RECONCILE, str(Path(__file__).resolve().parents[2] / "devpilot/src"), str(owned._path), run_id(owned)], cwd=owned._path.parent, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["state"] == "collected" and receipt["verdict"] == "NOT_EVALUATED"
    assert "PRIVATE" not in result.stdout + result.stderr


def test_hard_exit_with_wal_retains_unknown_no_resume(tmp_path):
    ident = str(uuid4())
    path = tmp_path / "crashed.sqlite"
    script = r"""
import os,sys
sys.path.insert(0,sys.argv[1])
from devpilot.local_json_run import LocalJSONJournal,LocalRunDefinition
from devpilot.qa_json_run import JSONRunLimits
j=LocalJSONJournal.create(sys.argv[2],LocalRunDefinition(sys.argv[3],'b'*64,1,JSONRunLimits(1,1,500,100000,64),100,65))
j.start(1000);j.reserve(1,10,1000)
os._exit(7)
"""
    result = subprocess.run([sys.executable, "-I", "-c", script, str(Path(__file__).resolve().parents[2] / "devpilot/src"), str(path), ident], capture_output=True, text=True, timeout=10)
    assert result.returncode == 7 and not result.stderr
    assert Path(str(path) + "-wal").is_file()
    receipt = module.reconcile(path, ident)
    assert receipt["state"] == "running" and receipt["attempt_states"]["dispatched"] == 1
    assert not receipt["resume_permitted"] and not receipt["resend_permitted"]
    assert receipt["output_content_verified"] is False


def test_same_path_owner_lock_fences_reconciliation_before_sqlite(owned, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager

    entered, opened = threading.Event(), threading.Event()
    ident = run_id(owned)
    actual_connection = LocalJSONJournal._connection
    actual_connect = sqlite3.connect

    @contextmanager
    def connection(self, **kwargs):
        entered.set()
        with actual_connection(self, **kwargs) as db:
            yield db

    def connect(*args, **kwargs):
        opened.set()
        return actual_connect(*args, **kwargs)

    monkeypatch.setattr(LocalJSONJournal, "_connection", connection)
    monkeypatch.setattr(sqlite3, "connect", connect)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with owned._lock:
            future = pool.submit(module.reconcile, owned._path, ident)
            assert entered.wait(3)
            assert not opened.is_set() and not future.done()
        receipt = future.result(timeout=3)
    assert opened.is_set() and receipt["state"] == "ready"


def test_source_replacement_during_read_never_returns_receipt(owned, monkeypatch):
    ident = run_id(owned)
    actual = module._regular
    calls = []

    def regular(path, **kwargs):
        result = actual(path, **kwargs)
        if path == owned._path:
            calls.append(path)
            if len(calls) == 2:
                return (result[0], result[1] + 1)
        return result

    monkeypatch.setattr(module, "_regular", regular)
    with pytest.raises(ValueError):
        module.reconcile(owned._path, ident)
    assert len(calls) == 2


def test_existing_cli_mock_execution_then_same_id_read_only_command(tmp_path):
    import runpy

    helpers = runpy.run_path(str(Path(__file__).with_name("test_local_qa_cli.py")))
    _, files = helpers["write_files"](tmp_path)
    source = str(Path(__file__).resolve().parents[2] / "devpilot/src")
    directory = tmp_path / "executed"
    executed = subprocess.run(
        [sys.executable, "-I", "-c", helpers["_ISOLATED_CLI"], source, *(str(files[name]) for name in ("manifest", "values", "inputs")), str(directory), "execute"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert executed.returncode == 0, executed.stderr
    summary = json.loads(executed.stdout)
    assert summary["state"] == "collected"
    journal_path = directory / "journal.sqlite"
    reconciled = subprocess.run([sys.executable, "-I", "-c", _ISOLATED_RECONCILE, source, str(journal_path), summary["run_id"]], cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert reconciled.returncode == 0, reconciled.stderr
    receipt = json.loads(reconciled.stdout)
    assert receipt["run_id"] == summary["run_id"]
    assert receipt["reserved_attempt_count"] == receipt["frozen_request_count"]
    assert receipt["observation_kinds"]["output_collected"] == receipt["frozen_request_count"]
    assert receipt["verdict"] == "NOT_EVALUATED" and receipt["output_content_verified"] is False
    assert not receipt["resend_permitted"] and not receipt["resume_permitted"]
    assert "SYNTHETIC" not in reconciled.stdout + reconciled.stderr
