"""Full local command, synthetic files, actual shared collector/run, no sockets."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest
from devpilot.local_json_run import LocalJSONJournal
from devpilot.local_qa_cli import LocalOutboundPolicy, LocalRunManifest, execute_local, main, preflight
from devpilot.pinned_http import EvaluationPolicyError, PinnedHTTPTransport
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_templates import RequestTemplate


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


def manifest(**changes):
    return LocalRunManifest(
        **{
            "template": RequestTemplate("POST", "https://example.test:443", ("Authorization",)),
            "binding": QAJSONBinding("/q", "/a"),
            "input_count": 2,
            "request_count": 5,
            "concurrency": 2,
            "timeout_ms": 1000,
            "duration_ms": 10000,
            "max_response_bytes": 128,
            "max_total_request_bytes": 4096,
            "max_total_response_bytes": 645,
            **changes,
        }
    )


def write_files(tmp_path, *, value=None, inputs=None):
    m = value or manifest()
    documents = {
        "manifest": m.to_dict(),
        "values": {
            "schema": "local-qa-values.v1",
            "bindings": {"DEVPILOT_REQUEST_URL": "https://example.test/private?secret=SYNTHETIC_QUERY", "DEVPILOT_REQUEST_BODY": '{"q":"","secret":"SYNTHETIC_BODY"}', "DEVPILOT_REQUEST_HEADER_1": "Bearer SYNTHETIC_TOKEN"},
        },
        "inputs": {"schema": "local-qa-inputs.v1", "inputs": ["SYNTHETIC_FIRST", "SYNTHETIC_SECOND"] if inputs is None else inputs},
    }
    paths = {}
    for key, payload in documents.items():
        paths[key] = tmp_path / (key + ".json")
        paths[key].write_text(json.dumps(payload), encoding="utf-8")
    return m, paths


def arguments(paths):
    return [part for key, path in paths.items() for part in ("--" + key, str(path))]


def update(paths, name, edit):
    payload = json.loads(paths[name].read_text())
    edit(payload)
    paths[name].write_text(json.dumps(payload))


@pytest.mark.parametrize(
    "name,value",
    [
        ("input_count", True),
        ("input_count", 0),
        ("input_count", 6),
        ("request_count", True),
        ("concurrency", 65),
        ("timeout_ms", 99),
        ("duration_ms", 999),
        ("duration_ms", 3600001),
        ("max_response_bytes", 0),
        ("max_total_request_bytes", 0),
        ("max_total_response_bytes", 128),
        ("template", RequestTemplate("POST", "http://example.test:80", ())),
    ],
)
def test_strict_manifest_definition(name, value):
    with pytest.raises(ValueError):
        manifest(**{name: value})


def test_manifest_roundtrip_value_free_and_fingerprint_not_secret_binding(tmp_path):
    m, files = write_files(tmp_path)
    assert LocalRunManifest.from_dict(m.to_dict()) == m
    text = json.dumps(m.to_dict()) + repr(m)
    assert all(value not in text for value in ["SYNTHETIC", "/private", "Bearer"])
    first = preflight(**{key + "_file": path for key, path in files.items()})
    update(files, "values", lambda d: d["bindings"].update(DEVPILOT_REQUEST_HEADER_1="OTHER_SECRET"))
    second = preflight(**{key + "_file": path for key, path in files.items()})
    assert first.manifest.fingerprint == second.manifest.fingerprint
    assert first.request != second.request
    assert "SYNTHETIC" not in repr(first) and "OTHER_SECRET" not in repr(second)


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(schema="unknown"),
        lambda d: d.update(scope="platform_verified"),
        lambda d: d.update(mode="acceptance"),
        lambda d: d.update(extra="unexpected"),
        lambda d: d["versions"].update(run="new-version"),
        lambda d: d["limits"].update(concurrency=1),
        lambda d: d.update(fingerprint="a" * 64),
    ],
)
def test_manifest_tampering_or_versions_fail_before_side_effects(tmp_path, edit):
    _, files = write_files(tmp_path)
    update(files, "manifest", edit)
    with pytest.raises(ValueError, match="Local QA preflight rejected"):
        preflight(**{key + "_file": path for key, path in files.items()})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["inputs.json", "manifest.json", "values.json"]


@pytest.mark.parametrize(
    "name,edit",
    [
        ("values", lambda d: d.update(gold="NEVER")),
        ("values", lambda d: d["bindings"].update(EXTRA="NEVER")),
        ("values", lambda d: d["bindings"].update(DEVPILOT_REQUEST_BODY=1)),
        ("values", lambda d: d["bindings"].update(DEVPILOT_REQUEST_URL="https://other.test/path")),
        ("values", lambda d: d["bindings"].update(DEVPILOT_REQUEST_BODY='{"not_q":""}')),
        ("inputs", lambda d: d.update(gold=["NEVER"])),
        ("inputs", lambda d: d.update(inputs=[{"input": "one", "gold": "NEVER"}, "two"])),
        ("inputs", lambda d: d.update(inputs=["one"])),
        ("inputs", lambda d: d.update(inputs=["one", ""])),
    ],
)
def test_separate_input_only_and_exact_secret_bindings_fail_closed(tmp_path, name, edit):
    _, files = write_files(tmp_path)
    update(files, name, edit)
    with pytest.raises(ValueError):
        preflight(**{key + "_file": path for key, path in files.items()})


@pytest.mark.parametrize(
    "content", [b'{"schema":1,"schema":2}', b'{"value":NaN}', b"\xff", b"[]", pytest.param(b"[" * 1100 + b"]" * 1100, id="excessive-nesting"), b'{"x":' + b"[" * 33 + b"0" + b"]" * 33 + b"}", pytest.param(b"x" * 32769, id="over-byte-limit")]
)
def test_malformed_bounded_manifest_files_have_generic_errors(tmp_path, content, capsys):
    _, files = write_files(tmp_path)
    files["manifest"].write_bytes(content)
    assert main(arguments(files)) == 1
    output = capsys.readouterr()
    assert not output.out and "Local QA rejected" in output.err
    assert "Traceback" not in output.err and "SYNTHETIC" not in output.err


@pytest.mark.parametrize("changes", [{"max_total_request_bytes": 1}, {"max_total_response_bytes": 644}])
def test_all_input_preflight_rejects_inadequate_cumulative_budget(tmp_path, changes):
    _, files = write_files(tmp_path, value=manifest(**changes))
    with pytest.raises(ValueError):
        preflight(**{key + "_file": path for key, path in files.items()})


def test_default_command_is_offline_without_output_directory(tmp_path, capsys, monkeypatch):
    m, files = write_files(tmp_path)
    monkeypatch.setenv("HTTP_PROXY", "http://SYNTHETIC_PROXY")
    monkeypatch.setenv("DEVPILOT_REQUEST_HEADER_1", "SYNTHETIC_ENV")
    assert main(arguments(files) + ["--results", str(tmp_path / "not_created")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["network_performed"] is False and result["verdict"] == "NOT_EVALUATED" and result["values_authenticated"] is False
    assert result["manifest_fingerprint"] == m.fingerprint and result["input_count"] == 2
    assert "SYNTHETIC" not in json.dumps(result) and not (tmp_path / "not_created").exists()


@pytest.mark.parametrize("flags", [[], ["--confirm-input-use"], ["--confirm-plaintext-output"], ["--confirm-input-use", "--confirm-plaintext-output", "--confirm-send", "wrong"]])
def test_each_execution_consent_is_required_before_files_or_dns(tmp_path, flags, capsys):
    _, files = write_files(tmp_path)
    assert main(arguments(files) + ["--execute", "--results", str(tmp_path / "results"), "--allow-host", "example.test", *flags]) == 1
    assert not (tmp_path / "results").exists()
    assert "SYNTHETIC" not in capsys.readouterr().err


@pytest.mark.parametrize("hosts", [(), ["example.test"], ("*",), ("EXAMPLE.TEST",), ("example.test:444",), ("example.test/path",), ("user@example.test",), ("example.test%eth0",)])
def test_exact_outbound_host_policy(hosts):
    with pytest.raises(ValueError):
        LocalOutboundPolicy(hosts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses,private,ok",
    [
        (["93.184.216.34"], False, True),
        (["93.184.216.34", "10.1.2.3"], False, False),
        (["10.1.2.3"], True, True),
        (["fc00::1"], True, True),
        (["127.0.0.1"], True, False),
        (["169.254.169.254"], True, False),
        (["0.0.0.0"], True, False),
        (["224.0.0.1"], True, False),
        (["::1"], True, False),
        (["::ffff:93.184.216.34"], True, False),
        (["fe80::1%eth0"], True, False),
        ([], False, False),
    ],
)
async def test_all_dns_answers_checked_and_private_is_explicit(tmp_path, monkeypatch, addresses, private, ok):
    _, files = write_files(tmp_path)
    prepared = preflight(**{key + "_file": path for key, path in files.items()})
    calls = []

    async def lookup(host, port, **kwargs):
        calls.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in addresses]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    policy = LocalOutboundPolicy(("example.test",), private)
    if ok:
        assert await policy.resolve(prepared.request) == addresses[0]
        assert await policy.resolve(prepared.request) == addresses[0]
        assert calls == [("example.test", 443)] * 2
    else:
        with pytest.raises(EvaluationPolicyError):
            await policy.resolve(prepared.request)
        assert len(calls) == 1


class Body(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"a":"SYNTHETIC_OUTPUT"}'

    async def aclose(self):
        pass


def mock_wire(monkeypatch, directory, *, status=200, failure=None):
    sent, closed = [], []
    actual_init = PinnedHTTPTransport.__init__

    def init(self, *args, **kwargs):
        actual_init(self, *args, **kwargs)

        async def send(request):
            snapshot = LocalJSONJournal.open(directory / "journal.sqlite").snapshot()
            assert len(snapshot.attempts) > len(sent)
            assert request.url.host == "93.184.216.34" and request.headers["host"] == "example.test"
            assert request.extensions["sni_hostname"] == "example.test"
            sent.append(request)
            if failure:
                raise failure
            return httpx.Response(status, headers={"content-type": "application/json"}, stream=Body())

        self.inner = httpx.MockTransport(send)
        original_close = self.inner.aclose

        async def close():
            closed.append(1)
            await original_close()

        self.inner.aclose = close

    async def lookup(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(PinnedHTTPTransport, "__init__", init)
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", lookup)
    return sent, closed


@pytest.mark.parametrize("concurrency,status", [(1, 200), (2, 200), (2, 503)])
def test_actual_cli_complete_shared_run_commit_before_pinned_wire_and_private_outputs(tmp_path, monkeypatch, capsys, concurrency, status):
    m, files = write_files(tmp_path, value=manifest(concurrency=concurrency))
    directory = tmp_path / "results"
    sent, closed = mock_wire(monkeypatch, directory, status=status)
    flags = ["--execute", "--results", str(directory), "--allow-host", "example.test", "--confirm-send", m.fingerprint, "--confirm-input-use", "--confirm-plaintext-output"]
    assert main(arguments(files) + flags) == 0
    printed = capsys.readouterr()
    assert "SYNTHETIC" not in printed.out + printed.err
    assert json.loads(printed.out)["verdict"] == "NOT_EVALUATED"
    assert len(sent) == 5 and len(closed) == 5
    bodies = [json.loads(req.content)["q"] for req in sent]
    assert bodies.count("SYNTHETIC_FIRST") == 3 and bodies.count("SYNTHETIC_SECOND") == 2
    rows = [json.loads(row) for row in (directory / "observations.jsonl").read_text().splitlines()]
    assert len(rows) == 7 and {row["verdict"] for row in rows} == {"NOT_EVALUATED"}
    assert {row["scope"] for row in rows} == {"external_unverified_technical_only"}
    assert rows[-1]["state"] == "collected" and sorted(row["ordinal"] for row in rows[1:-1]) == list(range(1, 6))
    assert all(row["output"] == ("SYNTHETIC_OUTPUT" if status == 200 else None) for row in rows[1:-1])
    content = (directory / "observations.jsonl").read_text()
    assert all(secret not in content for secret in ["SYNTHETIC_FIRST", "SYNTHETIC_SECOND", "SYNTHETIC_TOKEN", "SYNTHETIC_QUERY", "SYNTHETIC_BODY"])
    snapshot = LocalJSONJournal.open(directory / "journal.sqlite").snapshot()
    assert snapshot.state == "collected" and snapshot.reserved_response_bytes == 645
    if os.name == "posix":
        assert directory.stat().st_mode & 0o777 == 0o700
        assert (directory / "observations.jsonl").stat().st_mode & 0o777 == 0o600
    before = (directory / "observations.jsonl").read_bytes()
    assert main(arguments(files) + flags) == 1
    assert len(sent) == 5 and (directory / "observations.jsonl").read_bytes() == before


def test_uncertain_delivery_aborts_without_resend_and_retains_directory(tmp_path, monkeypatch, capsys):
    m, files = write_files(tmp_path, value=manifest(concurrency=1))
    directory = tmp_path / "results"
    sent, _ = mock_wire(monkeypatch, directory, failure=httpx.ReadError("SYNTHETIC_ERROR_SECRET"))
    flags = ["--execute", "--results", str(directory), "--allow-host", "example.test", "--confirm-send", m.fingerprint, "--confirm-input-use", "--confirm-plaintext-output"]
    assert main(arguments(files) + flags) == 1
    printed = capsys.readouterr()
    assert "SYNTHETIC" not in printed.out + printed.err and "Traceback" not in printed.err
    assert len(sent) == 1
    snapshot = LocalJSONJournal.open(directory / "journal.sqlite").snapshot()
    assert snapshot.state == "interrupted" and snapshot.attempts[0].state == "delivery_unknown"
    assert snapshot.reserved_response_bytes == 129 and directory.exists()


@pytest.mark.asyncio
async def test_repeated_cancel_drains_sensitive_output_write_before_final_journal_close(tmp_path, monkeypatch):
    import devpilot.local_qa_cli as cli

    _, files = write_files(tmp_path, value=manifest(concurrency=1))
    prepared = preflight(**{key + "_file": path for key, path in files.items()})
    directory = tmp_path / "results"
    sent, _ = mock_wire(monkeypatch, directory)
    entered, release, drained = threading.Event(), threading.Event(), threading.Event()
    real_append = cli._OutputStore.append

    def append(self, record):
        if "ordinal" in record:
            entered.set()
            assert release.wait(5)
            try:
                return real_append(self, record)
            finally:
                drained.set()
        return real_append(self, record)

    monkeypatch.setattr(cli._OutputStore, "append", append)
    task = asyncio.create_task(execute_local(prepared, directory, policy=LocalOutboundPolicy(("example.test",)), confirm_send=prepared.manifest.fingerprint, confirm_input_use=True, confirm_plaintext_output=True))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done() and not drained.is_set()
        assert LocalJSONJournal.open(directory / "journal.sqlite").snapshot().state == "running"
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError) and drained.is_set() and len(sent) == 1
    assert LocalJSONJournal.open(directory / "journal.sqlite").snapshot().state == "interrupted"


def test_argparse_errors_do_not_echo_values_or_tracebacks(capsys):
    assert main(["--not-a-flag", "SYNTHETIC_SECRET"]) == 1
    result = capsys.readouterr()
    assert "SYNTHETIC" not in result.err and "Traceback" not in result.err


@pytest.mark.parametrize("position", [1, 2, 3])
@pytest.mark.parametrize("failure", ["partial", "fsync"])
def test_output_failure_retains_journal_without_resend_or_repair(tmp_path, monkeypatch, capsys, position, failure):
    import devpilot.local_qa_cli as cli

    m, files = write_files(tmp_path, value=manifest(input_count=1, request_count=1, concurrency=1, max_total_response_bytes=129), inputs=["SYNTHETIC_FIRST"])
    directory = tmp_path / "results"
    sent, _ = mock_wire(monkeypatch, directory)
    real_write, real_fsync = cli.os.write, cli.os.fsync
    calls, closed = [], []
    real_append, real_close = cli._OutputStore.append, cli._OutputStore.close

    def append(self, record):
        calls.append(record)
        descriptor = self.descriptor

        def write(fd, data):
            if fd == descriptor and len(calls) == position:
                return real_write(fd, data[:5])
            return real_write(fd, data)

        def sync(fd):
            if fd == descriptor and len(calls) == position:
                raise OSError("SYNTHETIC_SECRET")
            return real_fsync(fd)

        monkeypatch.setattr(cli.os, "write", write if failure == "partial" else real_write)
        monkeypatch.setattr(cli.os, "fsync", sync if failure == "fsync" else real_fsync)
        return real_append(self, record)

    def close(self):
        real_close(self)
        closed.append(self.descriptor)

    monkeypatch.setattr(cli._OutputStore, "append", append)
    monkeypatch.setattr(cli._OutputStore, "close", close)
    flags = ["--execute", "--results", str(directory), "--allow-host", "example.test", "--confirm-send", m.fingerprint, "--confirm-input-use", "--confirm-plaintext-output"]
    assert main(arguments(files) + flags) == 1
    assert len(calls) == position and closed and all(value is None for value in closed)
    assert "SYNTHETIC" not in capsys.readouterr().err
    if position == 1:
        assert not sent and not (directory / "journal.sqlite").exists()
    else:
        snapshot = LocalJSONJournal.open(directory / "journal.sqlite").snapshot()
        assert len(sent) == 1 and snapshot.state == ("interrupted" if position == 2 else "collected")
    before = (directory / "observations.jsonl").read_bytes()
    assert main(arguments(files) + flags) == 1
    assert (directory / "observations.jsonl").read_bytes() == before


@pytest.mark.asyncio
async def test_cancellation_during_creation_drains_and_closes_both_resources(tmp_path, monkeypatch):
    import devpilot.local_qa_cli as cli

    _, files = write_files(tmp_path)
    prepared = preflight(**{key + "_file": path for key, path in files.items()})
    entered, release = threading.Event(), threading.Event()
    journals, outputs = [], []
    real_create, real_close = LocalJSONJournal.create, cli._OutputStore.close

    def create(*args):
        journal = real_create(*args)
        journals.append(journal)
        entered.set()
        assert release.wait(5)
        return journal

    def close(self):
        real_close(self)
        outputs.append(self.descriptor)

    monkeypatch.setattr(LocalJSONJournal, "create", create)
    monkeypatch.setattr(cli._OutputStore, "close", close)
    task = asyncio.create_task(execute_local(prepared, tmp_path / "results", policy=LocalOutboundPolicy(("example.test",)), confirm_send=prepared.manifest.fingerprint, confirm_input_use=True, confirm_plaintext_output=True))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert journals[0]._anchor is None and outputs == [None]
    assert journals[0].snapshot().state == "ready"


@pytest.mark.skipif(os.name != "posix", reason="POSIX file types")
@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_file_reader_rejects_nonregular_or_symlink_without_blocking(tmp_path, kind):
    from devpilot.local_qa_cli import _read_json

    path = tmp_path / "file"
    if kind == "symlink":
        (tmp_path / "target").write_text("{}")
        path.symlink_to(tmp_path / "target")
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(ValueError, match="Invalid local QA file"):
        _read_json(path, 32)


@pytest.mark.asyncio
async def test_dns_rebinding_fences_second_send_after_durable_reservation(tmp_path, monkeypatch):
    m, files = write_files(tmp_path, value=manifest(concurrency=1))
    directory = tmp_path / "results"
    sent, _ = mock_wire(monkeypatch, directory)
    calls = []

    async def lookup(host, port, **kwargs):
        calls.append(host)
        address = "93.184.216.34" if len(calls) == 1 else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    prepared = preflight(**{key + "_file": path for key, path in files.items()})
    with pytest.raises(EvaluationPolicyError):
        await execute_local(prepared, directory, policy=LocalOutboundPolicy(("example.test",)), confirm_send=m.fingerprint, confirm_input_use=True, confirm_plaintext_output=True)
    snapshot = LocalJSONJournal.open(directory / "journal.sqlite").snapshot()
    assert snapshot.state == "interrupted" and len(calls) == 2 and len(sent) == 1
    assert [row.state for row in snapshot.attempts] == ["observed", "observed"]
    assert [row.kind for row in snapshot.attempts] == ["output_collected", "policy_rejected"]


@pytest.mark.asyncio
async def test_explicit_tls_no_environment_redirects_or_retries(tmp_path, monkeypatch):
    real_transport = httpx.AsyncHTTPTransport
    options = []

    def transport(**kwargs):
        options.append(kwargs)
        return real_transport(**kwargs)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", transport)
    monkeypatch.setenv("HTTPS_PROXY", "http://SYNTHETIC_PROXY")
    monkeypatch.setenv("SSL_CERT_FILE", "/SYNTHETIC_MISSING_CERT")
    async with LocalOutboundPolicy(("example.test",)).client("https://example.test/a", timeout_seconds=1) as client:
        assert client.trust_env is False and client.follow_redirects is False
    assert options == [{"verify": True, "trust_env": False, "retries": 0}]


_ISOLATED_CLI = """import asyncio,importlib.abc,importlib.util,json,runpy,socket,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi','openpyxl'}:raise AssertionError('business import')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs):raise AssertionError('real network')
socket.getaddrinfo=denied;socket.socket.connect=denied;socket.socket.connect_ex=denied;socket.socket.sendto=denied
assert sys.argv[1] in importlib.util.find_spec('devpilot.local_qa_cli').origin
import httpx
from devpilot.pinned_http import PinnedHTTPTransport
from devpilot.local_json_run import LocalJSONJournal
sent=[]
original=PinnedHTTPTransport.__init__
directory=Path(sys.argv[5])
class Body(httpx.AsyncByteStream):
 async def __aiter__(self):yield b'{"a":"SYNTHETIC_OUTPUT"}'
 async def aclose(self):pass
def init(self,*args,**kwargs):
 original(self,*args,**kwargs)
 async def wire(request):
  snapshot=LocalJSONJournal.open(directory/'journal.sqlite').snapshot()
  assert len(snapshot.attempts)>len(sent)
  assert request.url.host=='93.184.216.34'
  assert request.headers['host']=='example.test' and request.extensions['sni_hostname']=='example.test'
  sent.append(request.content)
  return httpx.Response(200,headers={'content-type':'application/json'},stream=Body())
 self.inner=httpx.MockTransport(wire)
PinnedHTTPTransport.__init__=init
async def lookup(self,host,port,**kwargs):
 assert host=='example.test'
 return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',port))]
asyncio.BaseEventLoop.getaddrinfo=lookup
manifest=json.loads(Path(sys.argv[2]).read_text())
execute=sys.argv[6]=='execute'
sys.argv=['devpilot.local_qa_cli','--manifest',sys.argv[2],'--values',sys.argv[3],'--inputs',sys.argv[4]]
if execute:sys.argv+=['--execute','--results',str(directory),'--allow-host','example.test','--confirm-send',manifest['fingerprint'],'--confirm-input-use','--confirm-plaintext-output']
try:runpy.run_module('devpilot.local_qa_cli',run_name='__main__')
except SystemExit as outcome:assert outcome.code==0
if execute:
 assert len(sent)==5 and sent.count(b'{"q":"SYNTHETIC_FIRST","secret":"SYNTHETIC_BODY"}')==3
 snapshot=LocalJSONJournal.open(directory/'journal.sqlite').snapshot()
 assert snapshot.state=='collected' and snapshot.reserved_response_bytes==645
 rows=[json.loads(row) for row in (directory/'observations.jsonl').read_text().splitlines()]
 assert len(rows)==7 and all(row['verdict']=='NOT_EVALUATED' for row in rows)
else:assert not sent and not directory.exists()
assert not any(name.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi'} for name in sys.modules)
"""


@pytest.mark.parametrize("mode", ["offline", "execute"])
def test_actual_module_isolated_source_without_business_imports(tmp_path, mode):
    _, files = write_files(tmp_path)
    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    result = subprocess.run(
        [sys.executable, "-I", "-c", _ISOLATED_CLI, str(source), *(str(files[name]) for name in ("manifest", "values", "inputs")), str(tmp_path / "isolated"), mode], cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["verdict"] == "NOT_EVALUATED" and "SYNTHETIC" not in result.stdout + result.stderr
