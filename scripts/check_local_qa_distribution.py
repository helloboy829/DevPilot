"""CI-only fresh offline install and actual installed synthetic CLI verification.

Explicitly installs software in a NEW directory. Never sends a real request.
Not an end-user auto-installer or an untrusted-archive execution service.
"""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

# Resolve only the reviewed sibling source, including under python -I.
# Never add the working directory to sys.path or accept an installed namesake.
_builder_spec = importlib.util.spec_from_file_location("local_qa_distribution_builder", Path(__file__).resolve().with_name("build_local_qa_distribution.py"))
_builder = importlib.util.module_from_spec(_builder_spec)
_builder_spec.loader.exec_module(_builder)
archive_entries, native_target, read_regular, sha256 = _builder.archive_entries, _builder.native_target, _builder.read_regular, _builder.sha256

_INSTALLED_CHECK = r"""
import asyncio, contextlib, importlib.abc, importlib.util, io, json, runpy, socket, subprocess, sys
from pathlib import Path
assert sys.version_info[:2] == (3,12) and sys.prefix != sys.base_prefix
root, directory = Path(sys.argv[1]), Path(sys.argv[2])
for name in ('devpilot.local_qa_cli','devpilot.local_qa_reconcile','devpilot.local_qa_output','devpilot.local_qa_retention',
 'cryptography','cffi','pycparser','httpx','httpcore','h11','certifi','anyio','idna','typing_extensions','openpyxl','et_xmlfile'):
 origin = Path(importlib.util.find_spec(name).origin).resolve()
 assert origin.is_relative_to(Path(sys.prefix).resolve()), (name,str(origin))
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
sent=[]
original=PinnedHTTPTransport.__init__
class Body(httpx.AsyncByteStream):
 async def __aiter__(self): yield b'{"a":"SYNTHETIC_OUTPUT"}'
 async def aclose(self): pass
def snapshot():
 handle=LocalJSONJournal.open(directory/'journal.sqlite')
 try: return handle.snapshot()
 finally: handle.close()
def init(self,*args,**kwargs):
 original(self,*args,**kwargs)
 async def wire(request):
  identity=json.loads((directory/'run-receipt.json').read_text())
  state=snapshot()
  assert identity['run_id']==state.definition.run_id and not identity['resend_permitted']
  assert len(state.attempts)>len(sent)
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
def command(module,args):
 output=io.StringIO()
 sys.argv=[module,*args]
 with contextlib.redirect_stdout(output):
  try: runpy.run_module(module,run_name='__main__')
  except SystemExit as result: assert result.code==0
 return json.loads(output.getvalue())
arguments=[part for name in ('manifest','values','inputs') for part in ('--'+name,str(root/'examples'/(name+'.json')))]
preflight=command('devpilot.local_qa_cli',arguments)
assert preflight['schema']=='local-qa-preflight.v1' and preflight['network_performed'] is False
assert preflight['input_count']==2 and preflight['request_count']==5 and not sent and not directory.exists()
manifest=json.loads((root/'examples/manifest.json').read_text())
result=command('devpilot.local_qa_cli',arguments+['--execute','--results',str(directory),'--allow-host','example.test','--confirm-send',manifest['fingerprint'],'--confirm-input-use','--confirm-plaintext-output'])
assert result['state']=='collected' and result['verdict']=='NOT_EVALUATED'
assert len(sent)==5 and sent.count(b'{"q":"SYNTHETIC_FIRST","secret":"SYNTHETIC_BODY"}')==3
identity=json.loads((directory/'run-receipt.json').read_text())
assert identity['run_id']==result['run_id'] and not identity['resume_permitted']
receipt=command('devpilot.local_qa_reconcile',['--journal',str(directory/'journal.sqlite'),'--run-id',result['run_id']])
assert receipt['state']=='collected' and receipt['verdict']=='NOT_EVALUATED' and receipt['run_id']==result['run_id']
assert receipt['reserved_attempt_count']==receipt['frozen_request_count']==5 and receipt['frozen_input_count']==2
assert receipt['observation_kinds']['output_collected']==5 and not receipt['output_content_verified']
assert not receipt['resend_permitted'] and not receipt['resume_permitted'] and len(sent)==5
# The actual installed encrypted mode uses the SAME shared runner, not a fixture DTO.
legacy_directory=directory
directory=directory.parent/'encrypted-results'
sent.clear()
from cryptography.fernet import Fernet
from devpilot.local_qa_output import EncryptedOutputStore
original_append=EncryptedOutputStore._append
def retained_append(self,kind,record):
 if kind=='header':
  receipt=json.loads((directory/'retention-receipt.json').read_bytes())
  assert receipt['run_id']==self.binding['run_id'] and receipt['manifest_fingerprint']==manifest['fingerprint']
  assert receipt['created_at_ms']==self.binding['created_at_ms'] and receipt['expires_at_ms']==self.binding['expires_at_ms']
  assert receipt['input_count']==2 and receipt['request_count']==5 and not receipt['resend_permitted']
 return original_append(self,kind,record)
EncryptedOutputStore._append=retained_append
key=directory.parent/'synthetic-output-key'
key.write_bytes(Fernet.generate_key()); key.chmod(0o600)
result=command('devpilot.local_qa_cli',arguments+['--execute','--results',str(directory),'--allow-host','example.test','--confirm-send',manifest['fingerprint'],'--confirm-input-use','--output-key-file',str(key),'--output-retention-seconds','300','--confirm-encrypted-output'])
assert result['state']=='collected' and len(sent)==5
EncryptedOutputStore._append=original_append
assert not (directory/'observations.jsonl').exists()
assert all(b'SYNTHETIC_OUTPUT' not in p.read_bytes() for p in directory.iterdir() if p.is_file())
inspected=command('devpilot.local_qa_output',['inspect','--directory',str(directory),'--run-id',result['run_id'],'--manifest-fingerprint',manifest['fingerprint'],'--key-file',str(key)])
assert inspected['recorded_attempt_count']==5 and inspected['output_integrity_verified'] and not inspected['resend_permitted']
opened=directory.parent/'explicit-plaintext-open'
opened_result=command('devpilot.local_qa_output',['open','--directory',str(directory),'--run-id',result['run_id'],'--manifest-fingerprint',manifest['fingerprint'],'--key-file',str(key),'--destination',str(opened),'--confirm-sensitive-open'])
assert opened_result['sensitive_plaintext_created'] and b'SYNTHETIC_OUTPUT' in (opened/'observations.jsonl').read_bytes()
from devpilot.local_qa_output import purge_output
purged=purge_output(directory,key_file=key,expected_run_id=result['run_id'],expected_manifest_fingerprint=manifest['fingerprint'],confirm_ciphertext_sha256=inspected['ciphertext_sha256'],now_ms=lambda:inspected['expires_at_ms'])
assert purged['encrypted_file_removed'] and not purged['secure_erasure_proven']
reconciled=command('devpilot.local_qa_output',['reconcile-purge','--directory',str(directory),'--run-id',result['run_id'],'--manifest-fingerprint',manifest['fingerprint']])
assert reconciled['encrypted_file_absent'] and reconciled['completion_receipt_present'] and len(sent)==5
# Exercise real installed retention module commands in fresh processes.
from uuid import uuid4
from devpilot.local_qa_cli import LocalRunManifest
from devpilot.local_qa_retention import create_retention_receipt
retention_script = '''
import importlib.abc, runpy, socket, sys
from cryptography.fernet import Fernet
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi','langchain','langgraph'} or fullname in {'devpilot.local_qa_cli','devpilot.local_json_run','devpilot.pinned_http'}:
   raise AssertionError('business/execution import')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs): raise AssertionError('network/decryption forbidden')
socket.getaddrinfo=denied
for name in ('connect','connect_ex','sendto'): setattr(socket.socket,name,denied)
Fernet.decrypt=denied
sys.argv=['devpilot.local_qa_retention',*sys.argv[1:]]
runpy.run_module('devpilot.local_qa_retention',run_name='__main__')
'''
def retention_command(args,success=True):
 completed=subprocess.run([sys.executable,'-I','-c',retention_script,*args],cwd=directory.parent,capture_output=True,text=True,timeout=15)
 if not success:
  assert completed.returncode==1 and not completed.stdout and 'Local output' in completed.stderr
  return
 assert completed.returncode==0 and not completed.stderr, completed.stderr
 assert len(completed.stdout.splitlines())==1 and 'SYNTHETIC_INCOMPLETE_CIPHERTEXT' not in completed.stdout
 return json.loads(completed.stdout)
retention_directory=directory.parent/'incomplete-retention'
frozen=LocalRunManifest.from_dict(manifest)
original_id,disposal_id=str(uuid4()),str(uuid4())
with create_retention_receipt(retention_directory,original_id,frozen,retention_seconds=300,now_ms=lambda:1000):
 assert not (retention_directory/'observations.encrypted.jsonl').exists()
partial=retention_directory/'observations.encrypted.jsonl'
partial.write_bytes(b'SYNTHETIC_INCOMPLETE_CIPHERTEXT'); partial.chmod(0o600)
binding=['--directory',str(retention_directory),'--run-id',original_id,'--manifest-fingerprint',frozen.fingerprint]
inspection=retention_command(['inspect',*binding])
assert inspection['content_status']=='not_inspected' and not inspection['output_integrity_verified'] and inspection['expired']
for name in ('input_count','request_count','concurrency','timeout_ms','duration_ms','max_response_bytes','max_total_request_bytes','max_total_response_bytes'):
 assert inspection[name]==getattr(frozen,name)
disposal_args=['dispose-expired',*binding,'--disposal-id',disposal_id,'--confirm-ciphertext-sha256',inspection['source_ciphertext_sha256'],'--confirm-retention-receipt-sha256',inspection['retention_receipt_sha256']]
retention_command(disposal_args,success=False)
assert partial.read_bytes()==b'SYNTHETIC_INCOMPLETE_CIPHERTEXT'
disposed=retention_command([*disposal_args,'--confirm-incomplete-output-disposal'])
reconciled=retention_command(['reconcile-disposal',*binding,'--disposal-id',disposal_id])
assert disposed['output_removed'] and reconciled['completion_receipt_present'] and reconciled['output_absent']
assert not reconciled['secure_erasure_proven'] and not reconciled['resend_permitted'] and len(sent)==5
retention_command([*disposal_args,'--confirm-incomplete-output-disposal'],success=False)
assert not any(name.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi'} for name in sys.modules)
print(json.dumps({'fresh_venv_origins_verified':True,'all_runtime_dependencies_present':True,'real_dns_and_socket_sends_denied':True,'default_offline':True,'actual_installed_cli_mock_attempts':5,'actual_installed_encrypted_mock_attempts':5,'actual_installed_sensitive_open_and_expired_purge':True,'actual_installed_retention_disposal_and_reconciliation':True,'actual_installed_retention_commands':True,'pre_dispatch_receipt_at_every_wire':True,'actual_installed_same_id_reconciliation':True,'platform_provenance_verified':False,'verdict':'NOT_EVALUATED'},sort_keys=True))
"""


def run(command, *, cwd, expected_success=True):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if (result.returncode == 0) != expected_success:
        raise RuntimeError("Offline distribution verification failed")
    return result


def verify(archive, expected_hash, work):
    if sys.version_info[:2] != (3, 12) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("Python 3.12 and a separately trusted archive hash are required")
    data = read_regular(archive, 64 * 1024 * 1024)
    if sha256(data) != expected_hash:
        raise ValueError("Archive hash mismatch")
    files = archive_entries(data)
    manifest = json.loads(files.pop("distribution.json"))
    if manifest["schema"] != "local-qa-distribution.v2" or manifest["python"] != "3.12" or manifest["platform"] != native_target() or set(files) != set(manifest["files"]):
        raise ValueError("Archive manifest mismatch")
    for name, value in files.items():
        if manifest["files"][name] != {"sha256": sha256(value), "size": len(value)}:
            raise ValueError("Archive member hash mismatch")
    work.mkdir(mode=0o700)
    unpacked = work / "unpacked"
    unpacked.mkdir()
    for name, value in files.items():
        target = unpacked / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    venv = work / "venv"
    run([sys.executable, "-I", "-m", "venv", str(venv)], cwd=work)
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    install = [str(python), "-I", "-m", "pip", "--isolated", "install", "--no-index", "--find-links", str(unpacked / "wheels"), "--require-hashes", "--only-binary=:all:", "-r", str(unpacked / "requirements.lock")]
    # Prove actual installer rejection in the initially fresh venv, without
    # allowing a partial install; then restore the original trusted test bytes.
    dependency = unpacked / "wheels" / manifest["dependencies"]["httpx"]["filename"]
    saved = dependency.read_bytes()
    dependency.unlink()
    try:
        run([*install, "--dry-run"], cwd=work, expected_success=False)
    finally:
        dependency.write_bytes(saved)
    dependency.write_bytes(saved[:-1] + bytes([saved[-1] ^ 1]))
    try:
        failed_hash = run([*install, "--dry-run"], cwd=work, expected_success=False)
        if "HASHES" not in failed_hash.stderr.upper():
            raise RuntimeError("Expected actual hash rejection")
    finally:
        dependency.write_bytes(saved)
    run(install, cwd=work)
    run([str(python), "-I", "-m", "pip", "--isolated", "check"], cwd=work)
    result = run([str(python), "-I", "-c", _INSTALLED_CHECK, str(unpacked), str(work / "synthetic-run")], cwd=work)
    receipt = {"archive_sha256": expected_hash, "python": "3.12", "verification_platform": sys.platform, "missing_dependency_rejected": True, "tampered_dependency_rejected": True, **json.loads(result.stdout)}
    (work / "verification.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--work-directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive.resolve(), args.sha256, args.work_directory.resolve()), sort_keys=True))


if __name__ == "__main__":
    main()
