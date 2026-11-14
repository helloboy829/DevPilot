"""Explicit retention commands over real synthetic receipts; no sends or decryption."""

import hashlib
import json
import os
import socket
import subprocess
import sys
from uuid import uuid4

import pytest
from devpilot import local_qa_retention as retention
from test_local_qa_cli import manifest
from test_local_qa_retention import prepare


@pytest.fixture(autouse=True)
def no_network_or_decryption(monkeypatch):
    from cryptography.fernet import Fernet

    def denied(*args, **kwargs):
        raise AssertionError("No network or sensitive decryption")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)
    monkeypatch.setattr(Fernet, "decrypt", denied)


@pytest.fixture
def case(tmp_path):
    value = manifest()
    directory, receipt = prepare(tmp_path, value, output=b"SYNTHETIC_PARTIAL_OUTPUT_MUST_NOT_PRINT")
    return directory, receipt, value


def arguments(case, operation):
    directory, receipt, value = case
    return [operation, "--directory", str(directory), "--run-id", receipt["run_id"], "--manifest-fingerprint", value.fingerprint]


def disposal_arguments(case, *, disposal_id=None):
    directory, _, _ = case
    return arguments(case, "dispose-expired") + [
        "--disposal-id",
        disposal_id or str(uuid4()),
        "--confirm-retention-receipt-sha256",
        hashlib.sha256((directory / "retention-receipt.json").read_bytes()).hexdigest(),
        "--confirm-ciphertext-sha256",
        hashlib.sha256((directory / "observations.encrypted.jsonl").read_bytes()).hexdigest(),
        "--confirm-incomplete-output-disposal",
    ]


def contents(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


def result(capsys):
    captured = capsys.readouterr()
    assert not captured.err and len(captured.out.splitlines()) == 1
    assert "SYNTHETIC_PARTIAL_OUTPUT_MUST_NOT_PRINT" not in captured.out
    parsed = json.loads(captured.out)
    assert parsed["verdict"] == "NOT_EVALUATED"
    assert parsed["platform_provenance_verified"] is False
    assert parsed["resend_permitted"] is False and parsed["resume_permitted"] is False
    return parsed


def assert_error(capsys):
    captured = capsys.readouterr()
    assert not captured.out and captured.err == retention._ERROR + "\n"


def test_inspect_command_is_value_free_read_only_and_keeps_all_denominators(case, capsys):
    directory, receipt, value = case
    before = contents(directory)
    assert retention.main(arguments(case, "inspect")) == 0
    inspected = result(capsys)
    assert contents(directory) == before
    assert inspected["run_id"] == receipt["run_id"] and inspected["expired"]
    assert inspected["content_status"] == "not_inspected" and not inspected["output_integrity_verified"]
    assert inspected["source_ciphertext_sha256"] == hashlib.sha256(before["observations.encrypted.jsonl"]).hexdigest()
    for field in ("input_count", "request_count", "concurrency", "timeout_ms", "duration_ms", "max_response_bytes", "max_total_request_bytes", "max_total_response_bytes"):
        assert inspected[field] == getattr(value, field)


def test_dispose_and_same_id_reconcile_are_separate_commands(case, capsys):
    directory, _, _ = case
    before = contents(directory)
    disposal_id = str(uuid4())
    flags = disposal_arguments(case, disposal_id=disposal_id)
    assert retention.main(flags) == 0
    disposed = result(capsys)
    assert disposed["disposal_id"] == disposal_id and disposed["output_removed"]
    assert disposed["secure_erasure_proven"] is False
    assert not (directory / "observations.encrypted.jsonl").exists()
    assert (directory / "retention-receipt.json").read_bytes() == before["retention-receipt.json"]
    after = contents(directory)
    assert retention.main(arguments(case, "reconcile-disposal") + ["--disposal-id", disposal_id]) == 0
    reconciled = result(capsys)
    assert reconciled["completion_receipt_present"] and reconciled["output_absent"] and reconciled["read_only_reconciliation"]
    assert contents(directory) == after
    assert retention.main(flags) == 1
    assert_error(capsys)
    assert contents(directory) == after


def test_stdout_failure_after_disposal_preserves_original_id_reconciliation(case, capsys, monkeypatch):
    disposal_id = str(uuid4())
    flags = disposal_arguments(case, disposal_id=disposal_id)
    real_print = print

    def lost_stdout(*args, **kwargs):
        if kwargs.get("file") is not sys.stderr:
            raise BrokenPipeError("SYNTHETIC_LOST_STDOUT")
        return real_print(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(retention, "print", lost_stdout, raising=False)
        assert retention.main(flags) == 1
    assert_error(capsys)
    before = contents(case[0])
    assert retention.main(arguments(case, "reconcile-disposal") + ["--disposal-id", disposal_id]) == 0
    reconciled = result(capsys)
    assert reconciled["completion_receipt_present"] and reconciled["output_absent"]
    assert retention.main(flags) == 1
    assert_error(capsys)
    assert contents(case[0]) == before


def test_receipt_only_directory_is_observed_without_creating_output(tmp_path, capsys):
    value = manifest()
    directory, receipt = prepare(tmp_path, value, output=None)
    case = directory, receipt, value
    before = contents(directory)
    assert retention.main(arguments(case, "inspect")) == 0
    inspected = result(capsys)
    assert not inspected["output_present"] and inspected["source_ciphertext_sha256"] is None
    assert inspected["content_status"] == "not_inspected"
    assert contents(directory) == before


@pytest.mark.parametrize("field", ["--disposal-id", "--confirm-retention-receipt-sha256", "--confirm-ciphertext-sha256", "--confirm-incomplete-output-disposal"])
def test_missing_disposal_id_hash_or_separate_consent_never_writes(case, capsys, field):
    directory = case[0]
    flags = disposal_arguments(case)
    index = flags.index(field)
    del flags[index : index + (1 if field == "--confirm-incomplete-output-disposal" else 2)]
    before = contents(directory)
    assert retention.main(flags) == 1
    assert_error(capsys)
    assert contents(directory) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("--run-id", "invalid"),
        ("--run-id", str(uuid4())),
        ("--manifest-fingerprint", "0" * 64),
        ("--disposal-id", "invalid"),
        ("--confirm-retention-receipt-sha256", "0" * 64),
        ("--confirm-ciphertext-sha256", "0" * 64),
    ],
)
def test_wrong_original_bindings_do_not_create_an_intent(case, capsys, field, value):
    directory = case[0]
    flags = disposal_arguments(case)
    flags[flags.index(field) + 1] = value
    before = contents(directory)
    assert retention.main(flags) == 1
    assert_error(capsys)
    assert contents(directory) == before


@pytest.mark.parametrize(
    "operation,extra",
    [
        ("inspect", ["--disposal-id", str(uuid4())]),
        ("inspect", ["--confirm-incomplete-output-disposal"]),
        ("inspect", ["--key-file", "SYNTHETIC_PRIVATE_PATH"]),
        ("inspect", ["--now-ms", "999999999999999"]),
        ("inspect", ["--repair"]),
        ("inspect", ["--resume"]),
        ("inspect", ["--latest"]),
        ("reconcile-disposal", ["--disposal-id", str(uuid4()), "--confirm-incomplete-output-disposal"]),
    ],
)
def test_operation_specific_arguments_reject_extra_authority(case, capsys, operation, extra):
    before = contents(case[0])
    assert retention.main(arguments(case, operation) + extra) == 1
    assert_error(capsys)
    assert contents(case[0]) == before


@pytest.mark.parametrize("flags", [[], ["unknown"], ["inspect"], ["inspect", "--directory", "SYNTHETIC_PRIVATE_PATH"], ["--directory", "SYNTHETIC_PRIVATE_PATH"]])
def test_no_default_operation_or_directory_and_generic_parse_errors(capsys, flags):
    assert retention.main(flags) == 1
    assert_error(capsys)


@pytest.mark.parametrize("field", ["--directory", "--run-id", "--manifest-fingerprint", "--confirm-incomplete-output-disposal"])
def test_option_abbreviations_cannot_supply_identity_or_consent(case, capsys, field):
    flags = disposal_arguments(case)
    flags[flags.index(field)] = field[:-2]
    before = contents(case[0])
    assert retention.main(flags) == 1
    assert_error(capsys)
    assert contents(case[0]) == before


def test_not_yet_expired_never_writes_intent(case, capsys, monkeypatch):
    before = contents(case[0])
    monkeypatch.setattr(retention, "_clock", lambda _clock: case[1]["expires_at_ms"] - 1)
    assert retention.main(disposal_arguments(case)) == 1
    assert_error(capsys)
    assert contents(case[0]) == before


@pytest.mark.parametrize("part", ["retention.lock", "retention-receipt.json"])
def test_inspection_never_recreates_missing_files(case, capsys, part):
    (case[0] / part).unlink()
    before = contents(case[0])
    assert retention.main(arguments(case, "inspect")) == 1
    assert_error(capsys)
    assert contents(case[0]) == before


@pytest.mark.parametrize("failure", ["unlink", "after-unlink-sync", "completion-write", "interrupt"])
def test_unknown_disposal_only_reconciles_original_id_without_second_unlink(case, capsys, monkeypatch, failure):
    directory = case[0]
    disposal_id = str(uuid4())
    flags = disposal_arguments(case, disposal_id=disposal_id)
    real_unlink, real_sync, real_write = os.unlink, retention._sync_directory, retention._write_exclusive
    unlinks = []

    def unlink(path):
        unlinks.append(path)
        if failure == "unlink":
            raise OSError("SYNTHETIC_UNCERTAIN_DELETE")
        return real_unlink(path)

    def sync(path):
        if unlinks and failure == "after-unlink-sync":
            raise OSError("SYNTHETIC_UNCERTAIN_SYNC")
        return real_sync(path)

    def write(path, data):
        if path.name == "incomplete-output-disposal-complete.json" and failure == "completion-write":
            raise OSError("SYNTHETIC_UNCERTAIN_COMPLETION")
        real_write(path, data)
        if path.name == "incomplete-output-disposal-request.json" and failure == "interrupt":
            raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", unlink)
        patch.setattr(retention, "_sync_directory", sync)
        patch.setattr(retention, "_write_exclusive", write)
        assert retention.main(flags) == (130 if failure == "interrupt" else 1)
    assert_error(capsys)
    before = contents(directory)
    assert retention.main(arguments(case, "reconcile-disposal") + ["--disposal-id", disposal_id]) == 0
    reconciled = result(capsys)
    assert reconciled["disposal_id"] == disposal_id and not reconciled["completion_receipt_present"]
    assert reconciled["output_absent"] is (failure in ("after-unlink-sync", "completion-write"))
    assert contents(directory) == before
    assert retention.main(arguments(case, "reconcile-disposal") + ["--disposal-id", str(uuid4())]) == 1
    assert_error(capsys)
    assert retention.main(flags) == 1
    assert_error(capsys)
    changed_id = flags.copy()
    changed_id[changed_id.index("--disposal-id") + 1] = str(uuid4())
    assert retention.main(changed_id) == 1
    assert_error(capsys)
    assert len(unlinks) == (0 if failure == "interrupt" else 1)
    assert contents(directory) == before


_ISOLATED = """
import importlib.abc, runpy, socket, sys
from cryptography.fernet import Fernet
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi','langchain','langgraph'} or fullname in {'devpilot.local_qa_cli','devpilot.local_json_run','devpilot.pinned_http'}:
            raise AssertionError('No business/execution imports')
sys.meta_path.insert(0, Deny())
def denied(*args, **kwargs): raise AssertionError('No DNS, wire or decryption')
socket.getaddrinfo = denied
for name in ('connect','connect_ex','sendto'): setattr(socket.socket, name, denied)
Fernet.decrypt = denied
sys.argv = ['devpilot.local_qa_retention', *sys.argv[1:]]
runpy.run_module('devpilot.local_qa_retention', run_name='__main__')
"""


def run_module(flags, cwd):
    return subprocess.run([sys.executable, "-I", "-c", _ISOLATED, *flags], cwd=cwd, capture_output=True, text=True, timeout=10)


def test_real_module_commands_are_isolated_and_preserve_unverified_status(case, tmp_path):
    before = contents(case[0])
    inspected = run_module(arguments(case, "inspect"), tmp_path)
    assert inspected.returncode == 0 and not inspected.stderr
    value = json.loads(inspected.stdout)
    assert value["content_status"] == "not_inspected" and not value["output_integrity_verified"]
    assert contents(case[0]) == before
    disposal_id = str(uuid4())
    disposed = run_module(disposal_arguments(case, disposal_id=disposal_id), tmp_path)
    assert disposed.returncode == 0 and not disposed.stderr
    assert json.loads(disposed.stdout)["output_removed"]
    after = contents(case[0])
    reconciled = run_module(arguments(case, "reconcile-disposal") + ["--disposal-id", disposal_id], tmp_path)
    assert reconciled.returncode == 0 and not reconciled.stderr
    metadata = json.loads(reconciled.stdout)
    assert metadata["disposal_id"] == disposal_id and metadata["verdict"] == "NOT_EVALUATED"
    assert not metadata["platform_provenance_verified"] and not metadata["secure_erasure_proven"]
    assert contents(case[0]) == after
    assert "SYNTHETIC_PARTIAL_OUTPUT_MUST_NOT_PRINT" not in inspected.stdout + disposed.stdout + reconciled.stdout


def test_live_runtime_lease_makes_real_cli_fail_without_waiting(case, tmp_path):
    directory, _, value = case
    lease = retention._open_lock(directory, exclusive=True)
    before = contents(directory)
    try:
        for flags in (arguments(case, "inspect"), disposal_arguments(case)):
            captured = run_module(flags, tmp_path)
            assert captured.returncode == 1 and not captured.stdout
            assert captured.stderr == retention._ERROR + "\n"
    finally:
        os.close(lease)
    assert contents(directory) == before
    assert value.fingerprint == case[1]["manifest_fingerprint"]
