"""Explicit clean software distribution + synthetic HTTP export compatibility gate."""

import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from test_authorized_qa_exports import no_network as no_network
from test_authorized_qa_exports import open_url, setup_export
from test_evaluation_registry_router import api as api

from app.evaluation.authorized_exports import ExportRepository

# This is a synthetic CI verifier, never an installer for arbitrary user archives.
# -I and import-origin checks prevent checkout/system-site fallback in the child.
INSTALLED = r"""
import asyncio, contextlib, importlib.abc, importlib.util, io, json, runpy, socket, sys
from pathlib import Path
root, directory, software_hash = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
assert sys.version_info[:2] == (3,12) and sys.prefix != sys.base_prefix
for name in ('devpilot.local_qa_cli','devpilot.local_qa_reconcile','httpx','httpcore','h11','certifi','anyio','idna','typing_extensions','openpyxl','et_xmlfile'):
 assert Path(importlib.util.find_spec(name).origin).resolve().is_relative_to(Path(sys.prefix).resolve())
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi','langchain','langgraph'}: raise AssertionError('business import')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs): raise AssertionError('real network forbidden')
socket.getaddrinfo=denied
for name in ('connect','connect_ex','sendto'): setattr(socket.socket,name,denied)
import httpx
from devpilot.pinned_http import PinnedHTTPTransport
from devpilot.local_json_run import LocalJSONJournal
package=json.loads((root/'export.json').read_bytes())
assert package['software_archive_sha256']==software_hash
assert package['verdict']=='NOT_EVALUATED' and package['ready_for_preflight'] is False
assert package['all_frozen_samples']==1 and package['input_set_complete'] is True
values=json.loads((root/'values.example.json').read_bytes())
values['bindings'].update(DEVPILOT_REQUEST_URL='https://example.test/local',DEVPILOT_REQUEST_BODY='{"q":""}')
for name in values['bindings']:
 if name.startswith('DEVPILOT_REQUEST_HEADER_'): values['bindings'][name]='SYNTHETIC_LOCAL_ONLY'
(root/'values.json').write_text(json.dumps(values))
sent=[]
original=PinnedHTTPTransport.__init__
class Body(httpx.AsyncByteStream):
 async def __aiter__(self): yield b'{"a":"SYNTHETIC_INSTALLED_OUTPUT"}'
 async def aclose(self): pass
def init(self,*args,**kwargs):
 original(self,*args,**kwargs)
 async def wire(request):
  handle=LocalJSONJournal.open(directory/'journal.sqlite')
  try: state=handle.snapshot()
  finally: handle.close()
  identity=json.loads((directory/'run-receipt.json').read_bytes())
  assert identity['run_id']==state.definition.run_id
  assert len(state.attempts)==1 and state.attempts[0].state=='dispatched'
  assert not identity['resend_permitted']
  assert request.url.host=='93.184.216.34' and request.headers['host']=='example.test'
  assert request.extensions['sni_hostname']=='example.test'
  assert json.loads(request.content)=={'q':'Synthetic Q'}
  sent.append(1)
  return httpx.Response(200,headers={'content-type':'application/json'},stream=Body())
 self.inner=httpx.MockTransport(wire)
PinnedHTTPTransport.__init__=init
async def lookup(self,host,port,**kwargs):
 assert host=='example.test'
 return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',port))]
asyncio.BaseEventLoop.getaddrinfo=lookup
def command(module,args):
 output=io.StringIO()
 sys.argv=[module,*args]
 with contextlib.redirect_stdout(output):
  try: runpy.run_module(module,run_name='__main__')
  except SystemExit as result: assert result.code==0
 return json.loads(output.getvalue())
arguments=[part for name in ('manifest','values','inputs') for part in ('--'+name,str(root/(name+'.json')))]
preview=command('devpilot.local_qa_cli',arguments)
assert preview['network_performed'] is False and not sent and not directory.exists()
assert preview['input_count']==preview['request_count']==1
manifest=json.loads((root/'manifest.json').read_bytes())
result=command('devpilot.local_qa_cli',arguments+['--execute','--results',str(directory),'--allow-host','example.test','--confirm-send',manifest['fingerprint'],'--confirm-input-use','--confirm-plaintext-output'])
assert result['state']=='collected' and result['verdict']=='NOT_EVALUATED' and len(sent)==1
identity=json.loads((directory/'run-receipt.json').read_bytes())
assert identity['run_id']==result['run_id']
checked=command('devpilot.local_qa_reconcile',['--journal',str(directory/'journal.sqlite'),'--run-id',identity['run_id']])
assert checked['frozen_input_count']==checked['frozen_request_count']==checked['reserved_attempt_count']==1
assert checked['observation_kinds']['output_collected']==1
assert not checked['platform_provenance_verified'] and not checked['resend_permitted'] and not checked['resume_permitted']
assert len(sent)==1
print(json.dumps({'api_export_consumed':True,'installed_origins_verified':True,'default_offline':True,'mock_sends':1,'pre_dispatch_receipt_verified':True,'same_id_reconciliation':True,'verdict':'NOT_EVALUATED'}))
"""


def run(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.mark.skipif(not os.getenv("TEST_QA_SOFTWARE_ARCHIVE"), reason="Explicit trusted software archive required; separate distribution CI gate")
@pytest.mark.asyncio
async def test_http_export_consumed_by_actual_clean_offline_installed_cli(api, monkeypatch, tmp_path):
    client, app, _, _ = api
    archive = Path(os.environ["TEST_QA_SOFTWARE_ARCHIVE"]).resolve()
    expected_hash = os.environ["TEST_QA_SOFTWARE_SHA256"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected_hash
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    policy = repo._policy.model_dump()
    policy["software_archive_sha256"] = expected_hash
    app.state.evaluation_export_repo = ExportRepository(repo.sf, policy=policy, protection=repo._export_protection, clock_ms=repo.clock_ms)
    created = await client.put(path, json=payload)
    assert created.status_code == 200
    response = await client.get(open_url(path, created.json()))
    assert response.status_code == 200
    config = tmp_path / "exported-config"
    config.mkdir(mode=0o700)
    with zipfile.ZipFile(io.BytesIO(response.content)) as zipped:
        assert set(zipped.namelist()) == {"export.json", "manifest.json", "inputs.json", "values.example.json", "README.en.md", "README.zh.md"}
        for name in zipped.namelist():
            (config / name).write_bytes(zipped.read(name))
    root = Path(__file__).resolve().parents[2]
    work = tmp_path / "clean-offline-install"
    await asyncio.to_thread(run, [sys.executable, str(root / "scripts/check_local_qa_distribution.py"), "--archive", str(archive), "--sha256", expected_hash, "--work-directory", str(work)], tmp_path)
    installed_python = work / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    result = await asyncio.to_thread(run, [str(installed_python), "-I", "-c", INSTALLED, str(config), str(tmp_path / "results"), expected_hash], tmp_path)
    assert json.loads(result.stdout) == {
        "api_export_consumed": True,
        "installed_origins_verified": True,
        "default_offline": True,
        "mock_sends": 1,
        "pre_dispatch_receipt_verified": True,
        "same_id_reconciliation": True,
        "verdict": "NOT_EVALUATED",
    }


def test_ci_installed_export_gate_uses_separate_verified_software_artifact():
    import yaml

    root = Path(__file__).resolve().parents[2]
    jobs = yaml.safe_load((root / ".github/workflows/backend-unit-tests.yml").read_text(encoding="utf-8"))["jobs"]
    distribution = jobs["local-qa-distribution"]
    gate = jobs["authorized-export-installed"]
    assert gate["needs"] == "local-qa-distribution" and gate["runs-on"] == "ubuntu-latest"
    source_commands = "\n".join(step.get("run", "") for step in distribution["steps"])
    assert "uv sync" not in source_commands and "--no-deps" not in source_commands
    upload = next(step["with"] for step in distribution["steps"] if step.get("uses") == "actions/upload-artifact@v4")
    download = next(step["with"] for step in gate["steps"] if step.get("uses") == "actions/download-artifact@v4")
    assert upload["name"] == download["name"] == "local-qa-software-${{ github.sha }}"
    assert "local-qa-distribution.zip.sha256" in upload["path"] and upload["if-no-files-found"] == "error"
    commands = "\n".join(step.get("run", "") for step in gate["steps"])
    assert "sha256sum --check" in commands and "uv sync --frozen --group dev" in commands
    assert "TEST_QA_SOFTWARE_SHA256=" in commands and "test_authorized_qa_exports_installed.py" in commands
    assert "-q --tb=short" in commands and "--system-site-packages" not in commands
