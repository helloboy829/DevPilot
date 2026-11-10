"""Pre-dispatch technical identity receipt; real journal, no wire or sensitive reads."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from devpilot import local_qa_cli as cli
from devpilot.local_json_run import LocalJSONJournal
from devpilot.local_qa_reconcile import reconcile
from test_local_qa_cli import _ISOLATED_CLI, arguments, manifest, mock_wire, write_files
from test_local_qa_reconcile import _ISOLATED_RECONCILE


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


def flags(value, directory):
    return ["--execute", "--results", str(directory), "--allow-host", "example.test", "--confirm-send", value.fingerprint, "--confirm-input-use", "--confirm-plaintext-output"]


def receipt(directory):
    return json.loads((directory / "run-receipt.json").read_text())


def assert_identity(value, definition):
    assert value == {
        "schema": "local-qa-run-receipt.v1",
        "scope": "external_unverified_technical_only",
        "verdict": "NOT_EVALUATED",
        "receipt_kind": "pre_dispatch_identity_only",
        "run_id": definition.run_id,
        "manifest_fingerprint": definition.source_sha256,
        "frozen_input_count": definition.input_count,
        "frozen_request_count": definition.limits.request_count,
        "platform_provenance_verified": False,
        "resend_permitted": False,
        "resume_permitted": False,
    }
    assert str(UUID(value["run_id"])) == value["run_id"]
    assert len(json.dumps(value).encode()) < 1024
    assert "SYNTHETIC" not in json.dumps(value)


@pytest.mark.parametrize("concurrency", [1, 2])
def test_receipt_file_write_fsync_close_precedes_actual_start_and_wire(tmp_path, monkeypatch, capsys, concurrency):
    value, files = write_files(tmp_path, value=manifest(concurrency=concurrency))
    directory = tmp_path / "run"
    sent, _ = mock_wire(monkeypatch, directory)
    events, active = [], {}
    real_open, real_write, real_fsync, real_close = os.open, os.write, os.fsync, os.close
    real_start, real_reserve = LocalJSONJournal.start, LocalJSONJournal.reserve

    def open_file(file, *args):
        descriptor = real_open(file, *args)
        if Path(file).name == "run-receipt.json":
            assert args[0] & os.O_EXCL and args[1] == 0o600
            active["fd"] = descriptor
            events.append("open")
        return descriptor

    def write(descriptor, data):
        if descriptor == active.get("fd"):
            events.append("write")
        return real_write(descriptor, data)

    def sync(descriptor):
        if descriptor == active.get("fd"):
            events.append("fsync")
        return real_fsync(descriptor)

    def close(descriptor):
        if descriptor == active.get("fd"):
            events.append("close")
            active.clear()
        return real_close(descriptor)

    def start(self, *args):
        assert events == ["open", "write", "fsync", "close"] and not sent
        snapshot = self.snapshot()
        assert snapshot.state == "ready" and not snapshot.attempts
        assert_identity(receipt(directory), snapshot.definition)
        return real_start(self, *args)

    def reserve(self, *args):
        assert events == ["open", "write", "fsync", "close"]
        assert_identity(receipt(directory), self.snapshot().definition)
        return real_reserve(self, *args)

    for name, function in (("open", open_file), ("write", write), ("fsync", sync), ("close", close)):
        monkeypatch.setattr(os, name, function)
    monkeypatch.setattr(LocalJSONJournal, "start", start)
    monkeypatch.setattr(LocalJSONJournal, "reserve", reserve)
    assert cli.main(arguments(files) + flags(value, directory)) == 0
    printed = capsys.readouterr()
    assert len(printed.out.splitlines()) == 1 and not printed.err
    assert json.loads(printed.out)["run_id"] == receipt(directory)["run_id"]
    assert len(sent) == 5
    if os.name == "posix":
        assert (directory / "run-receipt.json").stat().st_mode & 0o777 == 0o600
    assert "state" not in receipt(directory)  # Identity receipt is not a stale success snapshot.


@pytest.mark.parametrize("failure", ["open", "write", "short", "zero", "fsync", "close"])
def test_receipt_uncertainty_aborts_before_start_without_retry_and_closes_resources(tmp_path, monkeypatch, capsys, failure):
    value, files = write_files(tmp_path)
    directory = tmp_path / "run"
    events, handles, active = [], {}, {}
    real_open, real_write, real_fsync, real_close = os.open, os.write, os.fsync, os.close
    real_create, real_store = LocalJSONJournal.create, cli._OutputStore.__init__

    def create(*args):
        handles["journal"] = real_create(*args)
        return handles["journal"]

    def store(self, *args):
        real_store(self, *args)
        handles["store"] = self

    def open_file(file, *args):
        if Path(file).name != "run-receipt.json":
            return real_open(file, *args)
        events.append("open")
        if failure == "open":
            raise OSError("SYNTHETIC_SECRET")
        descriptor = real_open(file, *args)
        handles["fd"] = active["fd"] = descriptor
        return descriptor

    def write(descriptor, data):
        if descriptor == active.get("fd"):
            events.append("write")
            if failure == "write":
                raise OSError("SYNTHETIC_SECRET")
            if failure in {"short", "zero"}:
                return real_write(descriptor, data[: len(data) // 2] if failure == "short" else b"")
        return real_write(descriptor, data)

    def sync(descriptor):
        if descriptor == active.get("fd"):
            events.append("fsync")
            if failure == "fsync":
                raise OSError("SYNTHETIC_SECRET")
        return real_fsync(descriptor)

    def close(descriptor):
        if descriptor == active.get("fd"):
            events.append("close")
            active.clear()
            real_close(descriptor)
            if failure == "close":
                raise OSError("SYNTHETIC_SECRET")
            return
        return real_close(descriptor)

    monkeypatch.setattr(LocalJSONJournal, "create", create)
    monkeypatch.setattr(cli._OutputStore, "__init__", store)
    for name, function in (("open", open_file), ("write", write), ("fsync", sync), ("close", close)):
        monkeypatch.setattr(os, name, function)
    assert cli.main(arguments(files) + flags(value, directory)) == 1
    printed = capsys.readouterr()
    assert not printed.out and "run-receipt.json" in printed.err
    assert "SYNTHETIC" not in printed.err and "Traceback" not in printed.err
    assert all(events.count(name) <= 1 for name in ("open", "write", "fsync", "close"))
    journal = handles["journal"]
    assert journal._token is None and journal._anchor is None
    assert handles["store"].descriptor is None
    snapshot = LocalJSONJournal.open(directory / "journal.sqlite").snapshot()
    assert snapshot.state == "ready" and not snapshot.attempts
    if "fd" in handles:
        with pytest.raises(OSError):
            os.fstat(handles["fd"])


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "fifo"])
def test_exclusive_receipt_collision_never_replaces_or_repairs(tmp_path, monkeypatch, capsys, kind):
    if kind in {"symlink", "fifo"} and os.name != "posix":
        pytest.skip("POSIX special file")
    value, files = write_files(tmp_path)
    directory = tmp_path / "run"
    original = cli._OutputStore.__init__
    target = tmp_path / "retained"
    target.write_bytes(b"RETAIN_ORIGINAL")

    def create_collision(self, *args):
        original(self, *args)
        file = directory / "run-receipt.json"
        if kind == "file":
            file.write_bytes(b"RETAIN_ORIGINAL")
        elif kind == "directory":
            file.mkdir()
        elif kind == "symlink":
            file.symlink_to(target)
        else:
            os.mkfifo(file)

    monkeypatch.setattr(cli._OutputStore, "__init__", create_collision)
    assert cli.main(arguments(files) + flags(value, directory)) == 1
    assert not capsys.readouterr().out
    assert target.read_bytes() == b"RETAIN_ORIGINAL"
    if kind == "file":
        assert (directory / "run-receipt.json").read_bytes() == b"RETAIN_ORIGINAL"
    snapshot = LocalJSONJournal.open(directory / "journal.sqlite").snapshot()
    assert snapshot.state == "ready" and not snapshot.attempts


@pytest.mark.parametrize("mode", ["offline", "missing_consent", "wrong_fingerprint", "wrong_host", "existing_directory"])
def test_pre_execution_rejection_or_offline_does_not_create_or_replace_receipt(tmp_path, monkeypatch, capsys, mode):
    value, files = write_files(tmp_path)
    directory = tmp_path / "run"
    args = arguments(files)
    if mode != "offline":
        args += flags(value, directory)
    if mode == "missing_consent":
        args.remove("--confirm-input-use")
    elif mode == "wrong_fingerprint":
        args[args.index("--confirm-send") + 1] = "0" * 64
    elif mode == "wrong_host":
        args[args.index("--allow-host") + 1] = "other.test"
    elif mode == "existing_directory":
        directory.mkdir()
        (directory / "run-receipt.json").write_bytes(b"RETAIN_ORIGINAL")
    assert cli.main(args) == (0 if mode == "offline" else 1)
    capsys.readouterr()
    if mode == "existing_directory":
        assert (directory / "run-receipt.json").read_bytes() == b"RETAIN_ORIGINAL"
        assert not (directory / "journal.sqlite").exists()
    else:
        assert not directory.exists()


def test_unknown_delivery_receipt_reconciles_same_id_without_opening_sensitive_output(tmp_path, monkeypatch, capsys):
    value, files = write_files(tmp_path, value=manifest(concurrency=1))
    directory = tmp_path / "run"
    sent, _ = mock_wire(monkeypatch, directory, failure=httpx.ReadError("SYNTHETIC_SECRET"))
    assert cli.main(arguments(files) + flags(value, directory)) == 1
    printed = capsys.readouterr()
    assert not printed.out and "SYNTHETIC" not in printed.err
    initial = (directory / "run-receipt.json").read_bytes()
    identity = receipt(directory)
    original = Path.open

    def open_file(self, *args, **kwargs):
        assert self.name != "observations.jsonl", "Sensitive output must not be opened"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    result = reconcile(directory / "journal.sqlite", identity["run_id"])
    assert result["state"] == "interrupted" and result["attempt_states"]["delivery_unknown"] == 1
    assert result["frozen_request_count"] == identity["frozen_request_count"] == 5
    assert result["declared_source_sha256"] == identity["manifest_fingerprint"]
    assert len(sent) == 1 and not result["resend_permitted"]
    assert cli.main(arguments(files) + flags(value, directory)) == 1
    assert len(sent) == 1 and (directory / "run-receipt.json").read_bytes() == initial


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_after_release", [False, True])
async def test_repeated_cancellation_drains_receipt_fsync_before_closing_and_never_starts(tmp_path, monkeypatch, fail_after_release):
    _, files = write_files(tmp_path)
    prepared = cli.preflight(**{key + "_file": file for key, file in files.items()})
    directory = tmp_path / "run"
    entered, release, drained = threading.Event(), threading.Event(), threading.Event()
    active, handles = {}, {}
    real_open, real_sync = os.open, os.fsync
    real_create, real_store = LocalJSONJournal.create, cli._OutputStore.__init__

    def open_file(file, *args):
        descriptor = real_open(file, *args)
        if Path(file).name == "run-receipt.json":
            active["fd"] = descriptor
        return descriptor

    def sync(descriptor):
        if descriptor != active.get("fd"):
            return real_sync(descriptor)
        entered.set()
        try:
            assert release.wait(5)
            assert handles["journal"]._token is not None and handles["store"].descriptor is not None
            real_sync(descriptor)
            if fail_after_release:
                raise OSError("SYNTHETIC_SECRET")
        finally:
            active.clear()
            drained.set()

    def create(*args):
        handles["journal"] = real_create(*args)
        return handles["journal"]

    def store(self, *args):
        real_store(self, *args)
        handles["store"] = self

    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(LocalJSONJournal, "create", create)
    monkeypatch.setattr(cli._OutputStore, "__init__", store)
    task = asyncio.create_task(cli.execute_local(prepared, directory, policy=cli.LocalOutboundPolicy(("example.test",)), confirm_send=prepared.manifest.fingerprint, confirm_input_use=True, confirm_plaintext_output=True))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and not drained.is_set()
        assert handles["journal"]._token is not None
        assert LocalJSONJournal.open(directory / "journal.sqlite").snapshot().state == "ready"
    finally:
        release.set()
        results = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError) and drained.is_set()
    assert handles["journal"]._token is None and handles["journal"]._anchor is None
    assert handles["store"].descriptor is None
    result = reconcile(directory / "journal.sqlite", receipt(directory)["run_id"])
    assert result["state"] == "ready" and result["reserved_attempt_count"] == 0


_ISOLATED_RECEIPT_CLI = _ISOLATED_CLI.replace(
    "snapshot=LocalJSONJournal.open(directory/'journal.sqlite').snapshot()",
    "identity=json.loads((directory/'run-receipt.json').read_text());assert identity['schema']=='local-qa-run-receipt.v1' and not identity['resend_permitted'];"
    "snapshot=LocalJSONJournal.open(directory/'journal.sqlite').snapshot();assert identity['run_id']==snapshot.definition.run_id",
)


@pytest.mark.parametrize("mode", ["offline", "execute"])
def test_actual_isolated_module_receipt_without_business_imports_or_real_wire(tmp_path, mode):
    _, files = write_files(tmp_path)
    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    result = subprocess.run(
        [sys.executable, "-I", "-c", _ISOLATED_RECEIPT_CLI, str(source), *(str(files[n]) for n in ("manifest", "values", "inputs")), str(tmp_path / "run"), mode], cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False
    )
    assert result.returncode == 0, result.stderr
    if mode == "execute":
        assert receipt(tmp_path / "run")["run_id"] == json.loads(result.stdout)["run_id"]
    else:
        assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("stage", ["receipt_ack", "dispatch"])
def test_hard_exit_retains_original_identity_and_never_grants_resume(tmp_path, stage):
    _, files = write_files(tmp_path, value=manifest(concurrency=1))
    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    script = _ISOLATED_RECEIPT_CLI.replace("import httpx", "import os,httpx")
    if stage == "dispatch":
        script = script.replace("sent.append(request.content)", "os._exit(29)")
    else:
        script = script.replace(
            "try:runpy.run_module",
            "real_open,real_sync=os.open,os.fsync;active={}\ndef open_file(file,*args):\n fd=real_open(file,*args)\n"
            " if Path(file).name=='run-receipt.json':active['fd']=fd\n return fd\ndef sync(fd):\n real_sync(fd)\n"
            " if fd==active.get('fd'):os._exit(29)\nos.open=open_file;os.fsync=sync\ntry:runpy.run_module",
        )
    directory = tmp_path / "run"
    result = subprocess.run([sys.executable, "-I", "-c", script, str(source), *(str(files[n]) for n in ("manifest", "values", "inputs")), str(directory), "execute"], cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 29 and not result.stdout and not result.stderr
    identity = receipt(directory)
    result = subprocess.run([sys.executable, "-I", "-c", _ISOLATED_RECONCILE, str(source), str(directory / "journal.sqlite"), identity["run_id"]], cwd=tmp_path, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    snapshot = json.loads(result.stdout)
    assert snapshot["run_id"] == identity["run_id"] and not snapshot["resume_permitted"] and not snapshot["resend_permitted"]
    assert snapshot["state"] == ("ready" if stage == "receipt_ack" else "running")
    assert snapshot["reserved_attempt_count"] == (0 if stage == "receipt_ack" else 1)
    assert snapshot["attempt_states"]["dispatched"] == (0 if stage == "receipt_ack" else 1)
    assert snapshot["output_content_verified"] is False


def test_journal_create_failure_has_no_receipt_or_send_and_closes_output(tmp_path, monkeypatch, capsys):
    value, files = write_files(tmp_path)
    directory = tmp_path / "run"
    stores = []
    real_store = cli._OutputStore.__init__

    def store(self, *args):
        real_store(self, *args)
        stores.append(self)

    def reject(*args):
        raise OSError("SYNTHETIC_SECRET")

    monkeypatch.setattr(cli._OutputStore, "__init__", store)
    monkeypatch.setattr(LocalJSONJournal, "create", reject)
    assert cli.main(arguments(files) + flags(value, directory)) == 1
    printed = capsys.readouterr()
    assert not printed.out and "SYNTHETIC" not in printed.err
    assert directory.exists() and not (directory / "run-receipt.json").exists()
    assert len(stores) == 1 and stores[0].descriptor is None


def test_final_output_failure_cannot_turn_identity_receipt_into_success_proof(tmp_path, monkeypatch, capsys):
    value, files = write_files(tmp_path)
    directory = tmp_path / "run"
    sent, _ = mock_wire(monkeypatch, directory)
    real_append = cli._OutputStore.append

    def append(self, record):
        if "state" in record:
            raise OSError("SYNTHETIC_SECRET")
        return real_append(self, record)

    monkeypatch.setattr(cli._OutputStore, "append", append)
    assert cli.main(arguments(files) + flags(value, directory)) == 1
    printed = capsys.readouterr()
    assert not printed.out and "SYNTHETIC" not in printed.err
    result = reconcile(directory / "journal.sqlite", receipt(directory)["run_id"])
    assert len(sent) == 5 and result["state"] == "collected" and result["output_content_verified"] is False
    assert "state" not in receipt(directory) and receipt(directory)["verdict"] == "NOT_EVALUATED"
