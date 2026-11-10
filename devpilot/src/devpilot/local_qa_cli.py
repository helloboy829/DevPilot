"""Explicit local execute-only QA command; never a platform export or approval.

Default preflight is offline. File bindings and input-only data are sensitive;
never log them or hash their plaintext. Output mode requires separate explicit
consent: operator-key encryption with retention, or legacy private plaintext. No environment configuration, plugins or auto-resume.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import socket
import stat
import sys
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from devpilot.local_json_run import LocalJSONJournal, LocalRunDefinition, _drained_database, run_local_json_attempts
from devpilot.local_qa_output import EncryptedOutputStore, LocalOutputProtection, _sync_directory
from devpilot.pinned_http import EvaluationPolicyError, PinnedHTTPTransport
from devpilot.qa_json_attempt import collect_json_attempt
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_run import JSONRunLimits
from devpilot.request_templates import RequestTemplate, fingerprint
from devpilot.request_versions import FrozenRequest

_SCOPE = "external_unverified_technical_only"
_VERSIONS = {"request": "request.v1", "binding": "qa-json-binding.v1", "run": "qa-json-run.v1", "attempt": "qa-json-attempt.v1", "transport": "pinned-http.v1", "journal": "local-qa-json-journal.v1"}


def _integer(value, lower, upper):
    return type(value) is int and lower <= value <= upper


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError


def _read_json(path, limit):
    """Read exactly an explicit bounded regular file; no stdin/env/remote URLs."""
    try:
        path = Path(path)
        if path.is_symlink():
            raise ValueError
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise ValueError
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_invalid_constant)
        stack = [(payload, 0)]
        count = 0
        while stack:
            value, depth = stack.pop()
            count += 1
            if depth > 32 or count > 20000:
                raise ValueError
            if isinstance(value, (dict, list)):
                stack.extend((child, depth + 1) for child in (value.values() if isinstance(value, dict) else value))
        return payload
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Invalid local QA file") from None


@dataclass(frozen=True, slots=True)
class LocalRunManifest:
    """Value-free wiring; a fingerprint is NOT a value binding or signature."""

    template: RequestTemplate = field(repr=False)
    binding: QAJSONBinding = field(repr=False)
    input_count: int
    request_count: int
    concurrency: int
    timeout_ms: int
    duration_ms: int
    max_response_bytes: int
    max_total_request_bytes: int
    max_total_response_bytes: int

    def __post_init__(self):
        try:
            if not isinstance(self.template, RequestTemplate) or not isinstance(self.binding, QAJSONBinding):
                raise ValueError
            if urlsplit(self.template.origin).scheme != "https":
                raise ValueError
            if not _integer(self.input_count, 1, min(500, self.request_count)) or not _integer(self.duration_ms, 1000, 3600000):
                raise ValueError
            self.definition(str(uuid4()), 1)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid local QA manifest") from None

    def _payload(self):
        return {
            "schema": "local-qa-json-manifest.v1",
            "scope": _SCOPE,
            "mode": "execute_only",
            "versions": dict(_VERSIONS),
            "request_template": self.template.to_dict(),
            "binding": self.binding.to_dict(),
            "input_count": self.input_count,
            "limits": {name: getattr(self, name) for name in ("request_count", "concurrency", "timeout_ms", "duration_ms", "max_response_bytes", "max_total_request_bytes", "max_total_response_bytes")},
        }

    @property
    def fingerprint(self):
        return fingerprint(self._payload())

    def to_dict(self):
        return {**self._payload(), "fingerprint": self.fingerprint}

    @classmethod
    def from_dict(cls, value):
        try:
            template = RequestTemplate.from_dict(value["request_template"])
            binding = QAJSONBinding.from_dict(value["binding"])
            manifest = cls(template, binding, value["input_count"], **value["limits"])
            if value != manifest.to_dict():
                raise ValueError
            return manifest
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError("Invalid local QA manifest") from None

    def definition(self, run_id, started_ms):
        limits = JSONRunLimits(self.request_count, self.concurrency, self.timeout_ms, started_ms + self.duration_ms, self.max_response_bytes)
        return LocalRunDefinition(run_id, self.fingerprint, self.input_count, limits, self.max_total_request_bytes, self.max_total_response_bytes)


@dataclass(frozen=True, slots=True)
class LocalPreflight:
    manifest: LocalRunManifest
    request: FrozenRequest = field(repr=False)
    inputs: tuple[str, ...] = field(repr=False)

    def summary(self):
        return {
            "schema": "local-qa-preflight.v1",
            "scope": _SCOPE,
            "mode": "execute_only",
            "manifest_fingerprint": self.manifest.fingerprint,
            "input_count": len(self.inputs),
            "request_count": self.manifest.request_count,
            "network_performed": False,
            "values_authenticated": False,
            "verdict": "NOT_EVALUATED",
            "sensitive_results": "private_plaintext_explicit_consent_required",
        }


def preflight(manifest_file, values_file, inputs_file):
    try:
        manifest = LocalRunManifest.from_dict(_read_json(manifest_file, 32768))
        values = _read_json(values_file, 524288)
        inputs = _read_json(inputs_file, 4194304)
        if type(values) is not dict or set(values) != {"schema", "bindings"} or values["schema"] != "local-qa-values.v1":
            raise ValueError
        wiring = manifest.template.to_dict()
        required = {wiring["url_ref"], wiring["body_ref"], *(ref for _, ref in wiring["headers"])}
        if type(values["bindings"]) is not dict or set(values["bindings"]) != required or any(type(v) is not str for v in values["bindings"].values()):
            raise ValueError
        if (
            type(inputs) is not dict
            or set(inputs) != {"schema", "inputs"}
            or inputs["schema"] != "local-qa-inputs.v1"
            or type(inputs["inputs"]) is not list
            or len(inputs["inputs"]) != manifest.input_count
            or any(type(v) is not str for v in inputs["inputs"])
        ):
            raise ValueError
        request = FrozenRequest.from_request(manifest.template.resolve(values["bindings"]))
        sizes = [len(manifest.binding.render(request, text).body.encode("utf-8")) for text in inputs["inputs"]]
        if any(size > 262144 for size in sizes):
            raise ValueError
        total = sum(sizes[n % len(sizes)] for n in range(manifest.request_count))
        if total > manifest.max_total_request_bytes or manifest.request_count * (manifest.max_response_bytes + 1) > manifest.max_total_response_bytes:
            raise ValueError
        return LocalPreflight(manifest, request, tuple(inputs["inputs"]))
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ValueError("Local QA preflight rejected") from None


@dataclass(frozen=True, slots=True)
class LocalOutboundPolicy:
    allowed_hosts: tuple[str, ...]
    allow_private: bool = False

    def __post_init__(self):
        try:
            if type(self.allowed_hosts) is not tuple or not self.allowed_hosts or len(self.allowed_hosts) > 32 or type(self.allow_private) is not bool:
                raise ValueError
            for host in self.allowed_hosts:
                if type(host) is not str or not host or host != host.lower() or "*" in host or "%" in host:
                    raise ValueError
                parsed = httpx.URL("https://" + ("[" + host + "]" if ":" in host else host))
                if parsed.host != host or parsed.raw_path != b"/" or (parsed.port or 443) != 443 or parsed.userinfo:
                    raise ValueError
        except (ValueError, TypeError, httpx.InvalidURL):
            raise ValueError("Invalid local outbound policy") from None

    def check_host(self, request):
        if httpx.URL(request.url).scheme != "https" or httpx.URL(request.url).host not in self.allowed_hosts:
            raise EvaluationPolicyError("Local destination not approved")

    async def resolve(self, request):
        self.check_host(request)
        answers = await asyncio.get_running_loop().getaddrinfo(httpx.URL(request.url).host, httpx.URL(request.url).port or 443, type=socket.SOCK_STREAM)
        try:
            addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
            if not addresses:
                raise ValueError
            private_ranges = tuple(ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
            for value in addresses:
                if type(value) is not str or "%" in value:
                    raise ValueError
                ip = ipaddress.ip_address(value)
                private = self.allow_private and any(ip in network for network in private_ranges if ip.version == network.version)
                if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved or ip.is_loopback or not (ip.is_global or private) or getattr(ip, "ipv4_mapped", None) is not None:
                    raise ValueError
            return addresses[0]
        except (ValueError, TypeError, IndexError):
            raise EvaluationPolicyError("Local DNS destination rejected") from None

    @asynccontextmanager
    async def client(self, url, *, timeout_seconds):
        async with httpx.AsyncClient(transport=PinnedHTTPTransport(url, self.resolve), timeout=timeout_seconds, trust_env=False, follow_redirects=False) as client:
            yield client


class _OutputStore:
    """Explicitly consented private plaintext; never platform review evidence."""

    def __init__(self, directory, run_id, manifest):
        directory = Path(directory).absolute()
        directory.mkdir(mode=0o700)  # Exclusive directory. Never repair or resume.
        self.path = directory / "observations.jsonl"
        self.lock = threading.Lock()
        self.maximum = manifest.max_total_response_bytes * 6 + manifest.request_count * 1024 + 4096
        self.size = 0
        self.descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.run_id = run_id
        try:
            self.append({"schema": "local-qa-observations.v1", "manifest_fingerprint": manifest.fingerprint, "input_count": manifest.input_count, "request_count": manifest.request_count, "sensitive_plaintext": True})
        except BaseException:
            self.close()
            raise

    def append(self, record):
        encoded = (json.dumps({"scope": _SCOPE, "verdict": "NOT_EVALUATED", "run_id": self.run_id, **record}, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self.lock:
            if self.size + len(encoded) > self.maximum:
                raise ValueError("Local result limit exceeded")
            # Keep the exclusive descriptor; never reopen a replaced path.
            # A partial/uncertain write aborts, never retries the record.
            if os.write(self.descriptor, encoded) != len(encoded):
                raise OSError("Local result write unconfirmed")
            os.fsync(self.descriptor)
            self.size += len(encoded)

    def close(self):
        with self.lock:
            if self.descriptor is not None:
                descriptor, self.descriptor = self.descriptor, None
                os.close(descriptor)


def _write_run_receipt(directory, run_id, manifest):
    """Fsync one identity-only receipt before dispatch; never repair or retry it."""
    payload = {
        "schema": "local-qa-run-receipt.v1",
        "scope": _SCOPE,
        "verdict": "NOT_EVALUATED",
        "receipt_kind": "pre_dispatch_identity_only",
        "run_id": run_id,
        "manifest_fingerprint": manifest.fingerprint,
        "frozen_input_count": manifest.input_count,
        "frozen_request_count": manifest.request_count,
        "platform_provenance_verified": False,
        "resend_permitted": False,
        "resume_permitted": False,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(Path(directory) / "run-receipt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise OSError("Local identity receipt write unconfirmed")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


async def execute_local(prepared, directory, *, policy, confirm_send, confirm_input_use, confirm_plaintext_output=False, output_protection=None, confirm_encrypted_output=False):
    """Read-once preflight values, explicit local consent; no platform authority."""
    if (
        not isinstance(prepared, LocalPreflight)
        or not isinstance(policy, LocalOutboundPolicy)
        or confirm_send != prepared.manifest.fingerprint
        or confirm_input_use is not True
        or (confirm_plaintext_output is not False and confirm_plaintext_output is not True)
        or (confirm_encrypted_output is not False and confirm_encrypted_output is not True)
    ):
        raise ValueError("Explicit local QA consent required")
    plaintext = confirm_plaintext_output is True and confirm_encrypted_output is False and output_protection is None
    encrypted = confirm_plaintext_output is False and confirm_encrypted_output is True and type(output_protection) is LocalOutputProtection
    if encrypted and output_protection.retention_seconds * 1000 < prepared.manifest.duration_ms:
        raise ValueError("Explicit local QA retention must cover the frozen run duration")
    if not plaintext and not encrypted:
        raise ValueError("Explicit local QA consent required")
    policy.check_host(prepared.request)
    holder = {}

    def now_ms():
        return time.monotonic_ns() // 1000000

    def create():
        run_id = str(uuid4())
        holder["output"] = EncryptedOutputStore(directory, run_id, prepared.manifest, output_protection) if encrypted else _OutputStore(directory, run_id, prepared.manifest)
        holder["journal"] = LocalJSONJournal.create(Path(directory) / "journal.sqlite", prepared.manifest.definition(run_id, now_ms()))
        _write_run_receipt(directory, run_id, prepared.manifest)
        if encrypted:
            _sync_directory(Path(directory))

    try:
        await _drained_database(create)
        store = holder["output"]

        async def collect(request, binding, limits):
            return await collect_json_attempt(request, binding, limits, client_factory=policy.client)

        async def record(ticket, observation):
            await _drained_database(
                store.append,
                {
                    "ordinal": ticket.ordinal,
                    "sample_index": ticket.sample_index,
                    "kind": observation.kind,
                    "http_status": observation.http_status,
                    "body_bytes": observation.body_bytes,
                    "elapsed_ms": observation.elapsed_ms,
                    "output": observation.output,
                },
            )

            if observation.kind == "policy_rejected":
                # Policy denial is known no-send, not uncertain delivery.
                # Stop this local run after durable recording; no later ordinals.
                raise EvaluationPolicyError("Local outbound policy stopped the run")

        async def active():
            policy.check_host(prepared.request)
            return True

        snapshot = await run_local_json_attempts(holder["journal"], prepared.request, prepared.manifest.binding, prepared.inputs, now_ms=now_ms, collect_attempt=collect, record_output=record, check_active=active)
        await _drained_database(store.append, {"state": snapshot.state, "reserved_request_bytes": snapshot.reserved_request_bytes, "reserved_response_bytes": snapshot.reserved_response_bytes})
        return snapshot
    finally:
        try:
            if "journal" in holder:
                await _drained_database(holder["journal"].close)
        finally:
            if "output" in holder:
                await _drained_database(holder["output"].close)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid local QA arguments")


def main(argv=None):
    parser = _Parser(description="Local execute-only QA. Default: OFFLINE preflight. Not platform export/approval. Choose explicit operator-key encrypted retention or legacy private plaintext; no default key.")
    for name in ("manifest", "values", "inputs"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--results")
    parser.add_argument("--allow-host", action="append", default=[])
    parser.add_argument("--allow-private-addresses", action="store_true")
    parser.add_argument("--confirm-send")
    parser.add_argument("--confirm-input-use", action="store_true")
    parser.add_argument("--confirm-plaintext-output", action="store_true")
    parser.add_argument("--confirm-encrypted-output", action="store_true")
    parser.add_argument("--output-key-file")
    parser.add_argument("--output-retention-seconds", type=int)
    try:
        args = parser.parse_args(argv)
        prepared = preflight(args.manifest, args.values, args.inputs)
        if not args.execute:
            print(json.dumps(prepared.summary(), sort_keys=True))
            return 0
        if not args.results:
            raise ValueError
        policy = LocalOutboundPolicy(tuple(args.allow_host), args.allow_private_addresses)
        protection = None
        if args.confirm_encrypted_output:
            if args.confirm_plaintext_output or not args.output_key_file or args.output_retention_seconds is None:
                raise ValueError
            protection = LocalOutputProtection.from_key_file(args.output_key_file, retention_seconds=args.output_retention_seconds)
            if Path(args.output_key_file).resolve().is_relative_to(Path(args.results).resolve()):
                raise ValueError
        elif args.output_key_file is not None or args.output_retention_seconds is not None:
            raise ValueError
        snapshot = asyncio.run(
            execute_local(
                prepared,
                args.results,
                policy=policy,
                confirm_send=args.confirm_send,
                confirm_input_use=args.confirm_input_use,
                confirm_plaintext_output=args.confirm_plaintext_output,
                output_protection=protection,
                confirm_encrypted_output=args.confirm_encrypted_output,
            )
        )
        print(json.dumps({"scope": _SCOPE, "run_id": snapshot.definition.run_id, "state": snapshot.state, "verdict": "NOT_EVALUATED"}, sort_keys=True))
        return 0 if snapshot.state == "collected" else 1
    except KeyboardInterrupt:
        print("Local QA cancelled; retain the same result directory and run-receipt.json for same-ID read-only reconciliation. Never auto-resend.", file=sys.stderr)
        return 130
    except Exception:
        print("Local QA rejected or interrupted. Retain any result directory and run-receipt.json for same-ID read-only reconciliation; no automatic retry or resend.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
