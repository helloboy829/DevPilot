"""Synthetic authenticated local outputs; never real DNS, wire or private files."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from devpilot.local_qa_cli import LocalOutboundPolicy, LocalRunManifest, execute_local, main, preflight
from devpilot.local_qa_output import LocalOutputProtection, inspect_output, open_output, purge_output, reconcile_purge
from devpilot.pinned_http import PinnedHTTPTransport
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_templates import RequestTemplate


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


@pytest.fixture
def case(tmp_path):
    manifest = LocalRunManifest(RequestTemplate("POST", "https://example.test:443", ("Authorization",)), QAJSONBinding("/q", "/a"), 2, 5, 2, 1000, 10000, 128, 4096, 645)
    documents = {
        "manifest": manifest.to_dict(),
        "values": {
            "schema": "local-qa-values.v1",
            "bindings": {"DEVPILOT_REQUEST_URL": "https://example.test/private?secret=SYNTHETIC_QUERY", "DEVPILOT_REQUEST_BODY": '{"q":"","secret":"SYNTHETIC_BODY"}', "DEVPILOT_REQUEST_HEADER_1": "Bearer SYNTHETIC_TOKEN"},
        },
        "inputs": {"schema": "local-qa-inputs.v1", "inputs": ["SYNTHETIC_FIRST", "SYNTHETIC_SECOND"]},
    }
    paths = {}
    for name, value in documents.items():
        paths[name] = tmp_path / (name + ".json")
        paths[name].write_text(json.dumps(value), encoding="utf-8")
    key = tmp_path / "synthetic-key"
    key.write_bytes(Fernet.generate_key())
    key.chmod(0o600)
    return manifest, paths, key


def arguments(paths):
    return [part for name, path in paths.items() for part in ("--" + name, str(path))]


def execute(case, directory, monkeypatch, **changes):
    manifest, paths, key = case
    sent = []

    async def lookup(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"a":"SYNTHETIC_OUTPUT"}'

        async def aclose(self):
            pass

    def respond(request):
        identity = json.loads((directory / "run-receipt.json").read_text())
        assert identity["manifest_fingerprint"] == manifest.fingerprint
        assert (directory / "observations.encrypted.jsonl").is_file()
        sent.append(request.content)
        return httpx.Response(200, stream=Body(), headers={"Content-Type": "application/json"})

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", lookup)
    original = PinnedHTTPTransport.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.inner = httpx.MockTransport(respond)

    monkeypatch.setattr(PinnedHTTPTransport, "__init__", init)
    prepared = preflight(paths["manifest"], paths["values"], paths["inputs"])
    options = {
        "policy": LocalOutboundPolicy(("example.test",)),
        "confirm_send": manifest.fingerprint,
        "confirm_input_use": True,
        "confirm_encrypted_output": True,
        "output_protection": LocalOutputProtection.from_key_file(key, retention_seconds=300),
    }
    options.update(changes)
    snapshot = asyncio.run(execute_local(prepared, directory, **options))
    return snapshot, sent


def inspect(case, directory, run_id, **changes):
    manifest, _, key = case
    return inspect_output(directory, key_file=key, expected_run_id=run_id, expected_manifest_fingerprint=manifest.fingerprint, **changes)


@pytest.mark.parametrize("value", [True, False, None, 0, 299, 2592001, "300", 300.0])
def test_strict_retention_rejected_before_output(case, value):
    with pytest.raises(ValueError, match="Local output"):
        LocalOutputProtection.from_key_file(case[2], retention_seconds=value)


@pytest.mark.parametrize("value", [b"", b"x" * 44, b"x" * 45, Fernet.generate_key() + b"\n", b" " + Fernet.generate_key()])
def test_invalid_key_is_generic_and_not_repaired(case, value):
    key = case[2]
    key.write_bytes(value)
    with pytest.raises(ValueError, match="Local output") as error:
        LocalOutputProtection.from_key_file(key, retention_seconds=300)
    assert str(key) not in str(error.value)
    assert key.read_bytes() == value


def test_key_permissions_links_and_repr(case, tmp_path):
    key = case[2]
    protection = LocalOutputProtection.from_key_file(key, retention_seconds=300)
    assert key.read_text() not in repr(protection)
    link = tmp_path / "key-link"
    link.symlink_to(key)
    with pytest.raises(ValueError):
        LocalOutputProtection.from_key_file(link, retention_seconds=300)
    if os.name == "posix":
        key.chmod(0o644)
        with pytest.raises(ValueError):
            LocalOutputProtection.from_key_file(key, retention_seconds=300)
        key.chmod(0o600)
        os.link(key, tmp_path / "key-hardlink")
        with pytest.raises(ValueError):
            LocalOutputProtection.from_key_file(key, retention_seconds=300)


def test_actual_shared_run_encrypted_and_same_id_reconciles(case, tmp_path, monkeypatch):
    directory = tmp_path / "protected"
    snapshot, sent = execute(case, directory, monkeypatch)
    assert snapshot.state == "collected" and len(sent) == 5
    assert not (directory / "observations.jsonl").exists()
    for path in directory.iterdir():
        if path.is_file():
            raw = path.read_bytes()
            assert all(secret not in raw for secret in (b"SYNTHETIC_OUTPUT", b"SYNTHETIC_BODY", b"SYNTHETIC_TOKEN", case[2].read_bytes()))
    result = inspect(case, directory, snapshot.definition.run_id)
    assert result["output_integrity_verified"] and result["final_record_verified"]
    assert result["recorded_attempt_count"] == 5
    assert result["verdict"] == "NOT_EVALUATED" and not result["platform_provenance_verified"]
    assert not result["resend_permitted"] and not result["resume_permitted"]
    assert "SYNTHETIC_OUTPUT" not in json.dumps(result)
    from devpilot.local_qa_reconcile import reconcile

    receipt = reconcile(directory / "journal.sqlite", snapshot.definition.run_id)
    assert receipt["reserved_attempt_count"] == 5
    assert not receipt["output_content_verified"]


@pytest.mark.parametrize("changes", [{"confirm_encrypted_output": False}, {"confirm_plaintext_output": True}, {"output_protection": None}, {"confirm_encrypted_output": 1}])
def test_separate_mode_consents_fail_before_directory_or_wire(case, tmp_path, monkeypatch, changes):
    directory = tmp_path / "protected"
    with pytest.raises(ValueError):
        execute(case, directory, monkeypatch, **changes)
    assert not directory.exists()


def test_offline_never_opens_key_or_output(case, tmp_path, capsys):
    missing = tmp_path / "missing-key"
    directory = tmp_path / "protected"
    assert main(arguments(case[1]) + ["--results", str(directory), "--output-key-file", str(missing), "--output-retention-seconds", "300", "--confirm-encrypted-output"]) == 0
    assert not directory.exists() and not missing.exists()
    assert json.loads(capsys.readouterr().out)["network_performed"] is False


@pytest.mark.parametrize("change", ["wrong-key", "wrong-run", "wrong-manifest", "header", "reorder", "duplicate", "splice", "truncated", "missing-final", "trailing", "oversize"])
def test_tampering_never_opens_sensitive_plaintext(case, tmp_path, monkeypatch, change):
    directory = tmp_path / "protected"
    snapshot, _ = execute(case, directory, monkeypatch)
    path = directory / "observations.encrypted.jsonl"
    lines = path.read_bytes().splitlines(keepends=True)
    key = case[2]
    run_id = snapshot.definition.run_id
    manifest_hash = case[0].fingerprint
    if change == "wrong-key":
        key = tmp_path / "wrong-key"
        key.write_bytes(Fernet.generate_key())
        key.chmod(0o600)
    elif change == "wrong-run":
        run_id = str(uuid4())
    elif change == "wrong-manifest":
        manifest_hash = "a" * 64
    elif change == "header":
        header = json.loads(lines[0])
        header["binding"]["expires_at_ms"] += 1
        lines[0] = (json.dumps(header) + "\n").encode()
    elif change == "reorder":
        lines[1], lines[2] = lines[2], lines[1]
    elif change == "duplicate":
        lines.insert(2, lines[1])
    elif change == "splice":
        other = tmp_path / "other"
        execute(case, other, monkeypatch)
        lines[2] = (other / path.name).read_bytes().splitlines(keepends=True)[2]
    elif change == "truncated":
        lines[-1] = lines[-1][:20]
    elif change == "missing-final":
        lines.pop()
    elif change == "trailing":
        lines.append(lines[-1])
    elif change == "oversize":
        lines[1] = b"x" * 100000 + b"\n"
    path.write_bytes(b"".join(lines))
    target = tmp_path / "opened"
    with pytest.raises(ValueError, match="Local output"):
        open_output(directory, key_file=key, expected_run_id=run_id, expected_manifest_fingerprint=manifest_hash, destination=target, confirm_sensitive_open=True)
    assert not target.exists()


def test_explicit_open_is_private_literal_and_expiry_blocks_it(case, tmp_path, monkeypatch):
    directory = tmp_path / "protected"
    snapshot, _ = execute(case, directory, monkeypatch)
    run_id = snapshot.definition.run_id
    before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    receipt = inspect(case, directory, run_id)
    options = {"key_file": case[2], "expected_run_id": run_id, "expected_manifest_fingerprint": case[0].fingerprint}
    with pytest.raises(ValueError):
        open_output(directory, destination=tmp_path / "denied", confirm_sensitive_open=False, **options)
    with pytest.raises(ValueError):
        open_output(directory, destination=tmp_path / "expired", confirm_sensitive_open=True, now_ms=lambda: receipt["expires_at_ms"], **options)
    assert not (tmp_path / "expired").exists()
    result = open_output(directory, destination=tmp_path / "opened", confirm_sensitive_open=True, **options)
    opened = tmp_path / "opened" / "observations.jsonl"
    rows = [json.loads(line) for line in opened.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 6 and sum(row.get("output") == "SYNTHETIC_OUTPUT" for row in rows) == 5
    assert result["sensitive_plaintext_created"] and "SYNTHETIC_OUTPUT" not in json.dumps(result)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    if os.name == "posix":
        assert opened.stat().st_mode & 0o777 == 0o600
        assert opened.parent.stat().st_mode & 0o777 == 0o700


def test_expired_exact_ciphertext_purge_preserves_identity_and_journal(case, tmp_path, monkeypatch):
    directory = tmp_path / "protected"
    snapshot, _ = execute(case, directory, monkeypatch)
    run_id = snapshot.definition.run_id
    receipt = inspect(case, directory, run_id)
    kept = {name: (directory / name).read_bytes() for name in ("journal.sqlite", "run-receipt.json")}
    options = {"key_file": case[2], "expected_run_id": run_id, "expected_manifest_fingerprint": case[0].fingerprint, "confirm_ciphertext_sha256": receipt["ciphertext_sha256"]}
    with pytest.raises(ValueError):
        purge_output(directory, **options)
    assert (directory / "observations.encrypted.jsonl").is_file()
    result = purge_output(directory, now_ms=lambda: receipt["expires_at_ms"], **options)
    assert result["encrypted_file_removed"] and not result["secure_erasure_proven"]
    assert not (directory / "observations.encrypted.jsonl").exists()
    assert kept == {name: (directory / name).read_bytes() for name in kept}
    assert all(result.get(name) is False for name in ("resend_permitted", "resume_permitted", "platform_provenance_verified"))
    reconciliation = reconcile_purge(directory, expected_run_id=run_id, expected_manifest_fingerprint=case[0].fingerprint)
    assert reconciliation["encrypted_file_absent"] and reconciliation["completion_receipt_present"]
    assert not reconciliation["resend_permitted"]


def test_wrong_purge_hash_never_creates_intent(case, tmp_path, monkeypatch):
    directory = tmp_path / "protected"
    snapshot, _ = execute(case, directory, monkeypatch)
    receipt = inspect(case, directory, snapshot.definition.run_id)
    with pytest.raises(ValueError):
        purge_output(directory, key_file=case[2], expected_run_id=snapshot.definition.run_id, expected_manifest_fingerprint=case[0].fingerprint, confirm_ciphertext_sha256="0" * 64, now_ms=lambda: receipt["expires_at_ms"])
    assert not (directory / "output-purge-request.json").exists()


@pytest.mark.parametrize("failure", ["short-write", "fsync"])
def test_uncertain_ciphertext_write_stops_run_without_second_record_or_resend(case, tmp_path, monkeypatch, failure):
    import devpilot.local_qa_output as output

    directory = tmp_path / "protected"
    original = output.EncryptedOutputStore.append
    calls = []

    def append(self, record):
        if "ordinal" not in record:
            return original(self, record)
        calls.append(record["ordinal"])
        write, sync = os.write, os.fsync

        def partial(descriptor, data):
            return write(descriptor, data[:15]) if descriptor == self.descriptor else write(descriptor, data)

        def unconfirmed(descriptor):
            if descriptor == self.descriptor:
                raise OSError("SYNTHETIC_FAILURE_SECRET")
            return sync(descriptor)

        with monkeypatch.context() as context:
            context.setattr(output.os, "write", partial if failure == "short-write" else write)
            context.setattr(output.os, "fsync", unconfirmed if failure == "fsync" else sync)
            return original(self, record)

    monkeypatch.setattr(output.EncryptedOutputStore, "append", append)
    with pytest.raises(Exception):
        execute(case, directory, monkeypatch)
    assert calls and len(calls) <= 2
    assert (directory / "run-receipt.json").exists()
    identity = json.loads((directory / "run-receipt.json").read_text())
    from devpilot.local_qa_reconcile import reconcile

    result = reconcile(directory / "journal.sqlite", identity["run_id"])
    assert result["state"] == "interrupted"
    assert result["reserved_attempt_count"] <= 2 and not result["resend_permitted"]
    with pytest.raises(ValueError):
        inspect(case, directory, identity["run_id"])


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_encryption_before_closing_journal(case, tmp_path, monkeypatch):
    import devpilot.local_qa_output as output
    from devpilot.local_json_run import LocalJSONJournal

    directory = tmp_path / "protected"
    entered, release = threading.Event(), threading.Event()
    original = output.EncryptedOutputStore.append
    closed = []
    original_close = output.EncryptedOutputStore.close

    def append(self, record):
        if "ordinal" in record:
            entered.set()
            assert release.wait(10)
        return original(self, record)

    def close(self):
        closed.append(True)
        return original_close(self)

    async def lookup(self, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"a":"SYNTHETIC_OUTPUT"}'

        async def aclose(self):
            pass

    original_init = PinnedHTTPTransport.__init__

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.inner = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "application/json"}, stream=Body()))

    monkeypatch.setattr(PinnedHTTPTransport, "__init__", init)
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", lookup)
    monkeypatch.setattr(output.EncryptedOutputStore, "append", append)
    monkeypatch.setattr(output.EncryptedOutputStore, "close", close)
    prepared = preflight(**{name + "_file": path for name, path in case[1].items()})
    task = asyncio.create_task(
        execute_local(
            prepared,
            directory,
            policy=LocalOutboundPolicy(("example.test",)),
            confirm_send=case[0].fingerprint,
            confirm_input_use=True,
            output_protection=LocalOutputProtection.from_key_file(case[2], retention_seconds=300),
            confirm_encrypted_output=True,
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        task.cancel()
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and not closed
        from devpilot.local_qa_retention import inspect_retention

        identity = json.loads((directory / "retention-receipt.json").read_bytes())
        with pytest.raises(ValueError, match="Local output"):
            inspect_retention(directory, expected_run_id=identity["run_id"], expected_manifest_fingerprint=case[0].fingerprint)
        journal = LocalJSONJournal.open(directory / "journal.sqlite")
        try:
            assert journal.snapshot().state == "running"
        finally:
            journal.close()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(closed) == 1
    assert inspect_retention(directory, expected_run_id=identity["run_id"], expected_manifest_fingerprint=case[0].fingerprint)["output_present"]
    journal = LocalJSONJournal.open(directory / "journal.sqlite")
    try:
        assert journal.snapshot().state == "interrupted"
    finally:
        journal.close()


@pytest.mark.parametrize("failure", ["unlink", "after-unlink-sync", "completion-write"])
def test_unknown_purge_never_deletes_again_and_only_same_id_reconciles(case, tmp_path, monkeypatch, failure):
    import devpilot.local_qa_output as output

    directory = tmp_path / "protected"
    snapshot, _ = execute(case, directory, monkeypatch)
    receipt = inspect(case, directory, snapshot.definition.run_id)
    unlink_calls = []
    original_unlink = output.os.unlink
    original_sync = output._sync_directory
    original_write = output._write_exclusive
    sync_calls = []

    def unlink(path):
        unlink_calls.append(str(path))
        if failure == "unlink":
            raise OSError("SYNTHETIC_UNCERTAIN_DELETE")
        return original_unlink(path)

    def sync(path):
        sync_calls.append(str(path))
        if failure == "after-unlink-sync" and len(sync_calls) == 2:
            raise OSError("SYNTHETIC_UNCERTAIN_SYNC")
        return original_sync(path)

    def write(path, data):
        if failure == "completion-write" and path.name == "output-purge-complete.json":
            raise OSError("SYNTHETIC_UNCERTAIN_RECEIPT")
        return original_write(path, data)

    options = {"key_file": case[2], "expected_run_id": snapshot.definition.run_id, "expected_manifest_fingerprint": case[0].fingerprint, "confirm_ciphertext_sha256": receipt["ciphertext_sha256"], "now_ms": lambda: receipt["expires_at_ms"]}
    with monkeypatch.context() as context:
        context.setattr(output.os, "unlink", unlink)
        context.setattr(output, "_sync_directory", sync)
        context.setattr(output, "_write_exclusive", write)
        with pytest.raises(ValueError, match="Local output"):
            purge_output(directory, **options)
    assert len(unlink_calls) == 1
    before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    result = reconcile_purge(directory, expected_run_id=snapshot.definition.run_id, expected_manifest_fingerprint=case[0].fingerprint)
    assert result["encrypted_file_absent"] is (failure != "unlink")
    assert not result["completion_receipt_present"] and not result["resend_permitted"]
    with pytest.raises(ValueError):
        purge_output(directory, **options)
    assert before == {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


def test_active_writer_excludes_inspection_and_purge(case, tmp_path):
    from devpilot.local_qa_output import EncryptedOutputStore

    directory = tmp_path / "protected"
    run_id = str(uuid4())
    store = EncryptedOutputStore(directory, run_id, case[0], LocalOutputProtection.from_key_file(case[2], retention_seconds=300))
    try:
        with pytest.raises(ValueError):
            inspect(case, directory, run_id)
        with pytest.raises(ValueError):
            purge_output(directory, key_file=case[2], expected_run_id=run_id, expected_manifest_fingerprint=case[0].fingerprint, confirm_ciphertext_sha256="0" * 64, now_ms=lambda: store.binding["expires_at_ms"])
        assert not (directory / "output-purge-request.json").exists()
    finally:
        store.close()


@pytest.mark.parametrize("part", ["file-symlink", "file-hardlink", "public-file", "directory-symlink", "public-directory"])
def test_output_filesystem_boundary_rejected(case, tmp_path, monkeypatch, part):
    directory = tmp_path / "protected"
    snapshot, _ = execute(case, directory, monkeypatch)
    path = directory / "observations.encrypted.jsonl"
    if part == "file-symlink":
        moved = tmp_path / "moved"
        path.rename(moved)
        path.symlink_to(moved)
    elif part == "file-hardlink":
        os.link(path, tmp_path / "linked")
    elif part == "public-file":
        path.chmod(0o644)
    elif part == "directory-symlink":
        link = tmp_path / "linked-directory"
        link.symlink_to(directory, target_is_directory=True)
        directory = link
    else:
        directory.chmod(0o755)
    with pytest.raises(ValueError):
        inspect(case, directory, snapshot.definition.run_id)


def test_cli_rejects_missing_key_mode_and_ambiguous_consents_before_wire(case, tmp_path, capsys):
    manifest, paths, key = case
    base = arguments(paths) + ["--execute", "--results", str(tmp_path / "protected"), "--allow-host", "example.test", "--confirm-send", manifest.fingerprint, "--confirm-input-use"]
    for flags in (
        ["--confirm-encrypted-output"],
        ["--output-key-file", str(key)],
        ["--output-key-file", str(key), "--output-retention-seconds", "300", "--confirm-plaintext-output"],
        ["--output-key-file", str(key), "--output-retention-seconds", "300", "--confirm-encrypted-output", "--confirm-plaintext-output"],
    ):
        assert main(base + flags) == 1
        captured = capsys.readouterr()
        assert not captured.out and str(key) not in captured.err and "SYNTHETIC" not in captured.err
        assert not (tmp_path / "protected").exists()


def test_sensitive_open_retains_same_source_descriptor_and_lock(case, tmp_path, monkeypatch):
    import devpilot.local_qa_output as output

    directory = tmp_path / "protected"
    snapshot, _ = execute(case, directory, monkeypatch)
    receipt = inspect(case, directory, snapshot.definition.run_id)
    original_open = output._open_read
    opened = []
    destination = tmp_path / "opened"
    original_directory = output._directory
    locked = []

    def tracked_open(path, limit):
        if path == directory / "observations.encrypted.jsonl":
            opened.append(path)
        return original_open(path, limit)

    def check_directory(path):
        if path == destination:
            with pytest.raises(ValueError):
                purge_output(
                    directory, key_file=case[2], expected_run_id=snapshot.definition.run_id, expected_manifest_fingerprint=case[0].fingerprint, confirm_ciphertext_sha256=receipt["ciphertext_sha256"], now_ms=lambda: receipt["expires_at_ms"]
                )
            locked.append(True)
            assert not (directory / "output-purge-request.json").exists()
        return original_directory(path)

    monkeypatch.setattr(output, "_open_read", tracked_open)
    monkeypatch.setattr(output, "_directory", check_directory)
    result = open_output(directory, key_file=case[2], expected_run_id=snapshot.definition.run_id, expected_manifest_fingerprint=case[0].fingerprint, destination=destination, confirm_sensitive_open=True)
    assert len(opened) == 2 and locked == [True]
    assert result["ciphertext_sha256"] == receipt["ciphertext_sha256"]
    assert result["recorded_attempt_count"] == 5
    assert b"SYNTHETIC_OUTPUT" in (destination / "observations.jsonl").read_bytes()


def test_future_authenticated_output_rejected_even_for_metadata(case, tmp_path, monkeypatch):
    directory = tmp_path / "protected"
    snapshot, _ = execute(case, directory, monkeypatch)
    receipt = inspect(case, directory, snapshot.definition.run_id)
    with pytest.raises(ValueError, match="Local output"):
        inspect(case, directory, snapshot.definition.run_id, now_ms=lambda: receipt["created_at_ms"] - 1)


def test_runtime_retention_is_durable_before_header_and_locked_until_close(case, tmp_path, monkeypatch):
    import devpilot.local_qa_output as output
    import devpilot.local_qa_retention as retention

    directory = tmp_path / "protected"
    events = []
    original_write = retention._write_exclusive
    original_append = output.EncryptedOutputStore._append
    original_close = output.EncryptedOutputStore.close

    def write(path, data):
        original_write(path, data)
        if path.name == "retention-receipt.json":
            events.append("durable-receipt")
            assert not (directory / "observations.encrypted.jsonl").exists()

    def check_locked(store):
        with pytest.raises(ValueError, match="Local output"):
            retention.inspect_retention(directory, expected_run_id=store.binding["run_id"], expected_manifest_fingerprint=case[0].fingerprint)

    def append(self, kind, record):
        if kind == "header":
            assert events == ["durable-receipt"]
            receipt = json.loads((directory / "retention-receipt.json").read_bytes())
            for field in ("run_id", "manifest_fingerprint", "created_at_ms", "expires_at_ms", "retention_seconds"):
                assert receipt[field] == self.binding[field]
            for field in retention._FROZEN:
                assert receipt[field] == getattr(case[0], field)
            events.append("header")
        check_locked(self)
        return original_append(self, kind, record)

    def close(self):
        check_locked(self)
        original_close(self)
        events.append("closed")

    monkeypatch.setattr(retention, "_write_exclusive", write)
    monkeypatch.setattr(output.EncryptedOutputStore, "_append", append)
    monkeypatch.setattr(output.EncryptedOutputStore, "close", close)
    snapshot, sent = execute(case, directory, monkeypatch)
    assert events == ["durable-receipt", "header", "closed"] and len(sent) == 5
    receipt = retention.inspect_retention(directory, expected_run_id=snapshot.definition.run_id, expected_manifest_fingerprint=case[0].fingerprint)
    assert receipt["output_present"] and not receipt["output_integrity_verified"]
    assert receipt["verdict"] == "NOT_EVALUATED" and not receipt["resend_permitted"]


@pytest.mark.parametrize("failure", ["short-write", "fsync", "close", "directory-sync"])
def test_uncertain_runtime_retention_never_creates_output_or_retries(case, tmp_path, monkeypatch, failure):
    import devpilot.local_qa_retention as retention

    directory = tmp_path / "protected"
    original_write = retention._write_exclusive
    attempts = []

    def fail(*_args):
        raise OSError("SYNTHETIC_UNCERTAIN_RETENTION")

    def write(path, data):
        if path.name != "retention-receipt.json":
            return original_write(path, data)
        attempts.append(path.name)
        real_write, real_close = os.write, os.close

        def close(descriptor):
            real_close(descriptor)
            fail()

        with monkeypatch.context() as patch:
            if failure == "short-write":
                patch.setattr(os, "write", lambda fd, payload: real_write(fd, payload[:1]))
            elif failure == "fsync":
                patch.setattr(os, "fsync", fail)
            elif failure == "close":
                patch.setattr(os, "close", close)
            else:
                patch.setattr(retention, "_sync_directory", fail)
            return original_write(path, data)

    monkeypatch.setattr(retention, "_write_exclusive", write)
    for _ in range(2):
        with pytest.raises(ValueError, match="Local output"):
            execute(case, directory, monkeypatch)
        assert attempts == ["retention-receipt.json"]
        assert not (directory / "observations.encrypted.jsonl").exists()
        assert not (directory / "journal.sqlite").exists()
        assert not (directory / "run-receipt.json").exists()


@pytest.mark.parametrize("failure", ["open", "header", "directory-sync"])
def test_output_creation_failure_leaves_original_retention_readable(case, tmp_path, monkeypatch, failure):
    import devpilot.local_qa_output as output
    from devpilot.local_qa_retention import inspect_retention

    directory = tmp_path / "protected"
    real_open = os.open

    def fail(*_args):
        raise OSError("SYNTHETIC_OUTPUT_CREATION_FAILURE")

    def open_file(path, *args):
        if Path(path).name == "observations.encrypted.jsonl":
            fail()
        return real_open(path, *args)

    with monkeypatch.context() as patch:
        if failure == "open":
            patch.setattr(os, "open", open_file)
        elif failure == "header":
            patch.setattr(output.EncryptedOutputStore, "_append", fail)
        else:
            patch.setattr(output, "_sync_directory", fail)
        with pytest.raises(OSError, match="SYNTHETIC_OUTPUT_CREATION_FAILURE"):
            execute(case, directory, monkeypatch)
    receipt = json.loads((directory / "retention-receipt.json").read_bytes())
    result = inspect_retention(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=case[0].fingerprint)
    assert result["output_present"] is (failure != "open")
    assert not result["output_integrity_verified"] and not result["resend_permitted"]
    assert not (directory / "journal.sqlite").exists()


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_retention_creation_before_releasing_lock(case, tmp_path, monkeypatch):
    import devpilot.local_qa_retention as retention

    directory = tmp_path / "protected"
    entered, release = threading.Event(), threading.Event()
    original = retention._write_exclusive
    calls = []

    def write(path, data):
        if path.name == "retention-receipt.json":
            calls.append(path.name)
            entered.set()
            assert release.wait(10)
        return original(path, data)

    monkeypatch.setattr(retention, "_write_exclusive", write)
    prepared = preflight(**{name + "_file": path for name, path in case[1].items()})
    task = asyncio.create_task(
        execute_local(
            prepared,
            directory,
            policy=LocalOutboundPolicy(("example.test",)),
            confirm_send=case[0].fingerprint,
            confirm_input_use=True,
            output_protection=LocalOutputProtection.from_key_file(case[2], retention_seconds=300),
            confirm_encrypted_output=True,
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and not (directory / "observations.encrypted.jsonl").exists()
    finally:
        release.set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    receipt = json.loads((directory / "retention-receipt.json").read_bytes())
    result = retention.inspect_retention(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=case[0].fingerprint)
    assert calls == ["retention-receipt.json"]
    assert result["output_present"] and not result["final_record_verified"]
    assert json.loads((directory / "run-receipt.json").read_bytes())["run_id"] == receipt["run_id"]


@pytest.mark.parametrize("stage", ["receipt", "header", "attempt"])
def test_actual_cli_hard_exit_preserves_retention_identity_without_resuming(case, tmp_path, stage):
    from devpilot.local_qa_retention import dispose_incomplete_output, inspect_retention, reconcile_incomplete_disposal

    directory = tmp_path / "protected"
    script = """
import asyncio, os, runpy, socket, sys
import httpx
from devpilot.local_qa_output import EncryptedOutputStore
import devpilot.local_qa_retention as retention
from devpilot.pinned_http import PinnedHTTPTransport
stage, flags = sys.argv[1], sys.argv[2:]
def denied(*args, **kwargs): raise AssertionError("Real network forbidden")
socket.getaddrinfo = denied
for name in ("connect", "connect_ex", "sendto"): setattr(socket.socket, name, denied)
async def lookup(self, host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
asyncio.BaseEventLoop.getaddrinfo = lookup
class Body(httpx.AsyncByteStream):
    async def __aiter__(self): yield b'{"a":"SYNTHETIC_OUTPUT"}'
    async def aclose(self): pass
original_init = PinnedHTTPTransport.__init__
def init(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    self.inner = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type":"application/json"}, stream=Body()))
PinnedHTTPTransport.__init__ = init
original_write = retention._write_exclusive
def write(path, data):
    original_write(path, data)
    if stage == "receipt" and path.name == "retention-receipt.json": os._exit(23)
retention._write_exclusive = write
original_append = EncryptedOutputStore._append
def append(self, kind, record):
    original_append(self, kind, record)
    if kind == stage: os._exit(23)
EncryptedOutputStore._append = append
sys.argv = ["devpilot.local_qa_cli", *flags]
runpy.run_module("devpilot.local_qa_cli", run_name="__main__")
"""
    flags = arguments(case[1]) + [
        "--execute",
        "--results",
        str(directory),
        "--allow-host",
        "example.test",
        "--confirm-send",
        case[0].fingerprint,
        "--confirm-input-use",
        "--confirm-encrypted-output",
        "--output-key-file",
        str(case[2]),
        "--output-retention-seconds",
        "300",
    ]
    result = subprocess.run([sys.executable, "-I", "-c", script, stage, *flags], cwd=tmp_path, capture_output=True, timeout=10)
    assert result.returncode == 23, result.stderr
    receipt = json.loads((directory / "retention-receipt.json").read_bytes())
    before = {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    options = {"expected_run_id": receipt["run_id"], "expected_manifest_fingerprint": case[0].fingerprint}
    inspection = inspect_retention(directory, **options)
    assert inspection["output_present"] is (stage != "receipt")
    assert not inspection["output_integrity_verified"]
    assert not inspection["resume_permitted"] and not inspection["resend_permitted"]
    assert before == {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}
    with pytest.raises(ValueError):
        inspect(case, directory, receipt["run_id"])
    assert (directory / "journal.sqlite").exists() is (stage == "attempt")
    if stage != "receipt":
        disposal_id = str(uuid4())
        dispose_incomplete_output(
            directory,
            **options,
            source_ciphertext_sha256=inspection["source_ciphertext_sha256"],
            retention_receipt_sha256=inspection["retention_receipt_sha256"],
            disposal_id=disposal_id,
            confirm_incomplete_output_disposal=True,
            now_ms=lambda: receipt["expires_at_ms"],
        )
        reconciled = reconcile_incomplete_disposal(directory, **options, disposal_id=disposal_id)
        assert reconciled["output_absent"] and reconciled["completion_receipt_present"] and not reconciled["secure_erasure_proven"]
        assert all((directory / name).read_bytes() == data for name, data in before.items() if name != "observations.encrypted.jsonl")
