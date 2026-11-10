"""Offline SAME-ID technical reconciliation; never resume or trusted evidence.

Only trusted local journals are supported, not hostile SQLite uploads. No output,
input, credentials or gold is opened. SQLite read-only transactions can maintain
WAL/SHM bookkeeping; no run/attempt record is modified. No network capability.
"""

from __future__ import annotations

import argparse
import json
import math
import stat
import sys
from collections import Counter
from pathlib import Path
from uuid import UUID

from devpilot.local_json_run import LocalJournalUnconfirmed, LocalJSONJournal

_SCOPE = "external_unverified_technical_only"
_KINDS = frozenset({"output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output", "delivery_unknown", "policy_rejected"})
_MAX_FILE_BYTES = 16 * 1024 * 1024


def _integer(value, lower, upper):
    return type(value) is int and lower <= value <= upper


def _regular(path, *, optional=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise
    if not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= _MAX_FILE_BYTES:
        raise ValueError
    return info.st_dev, info.st_ino


def _validate(snapshot, run_id):
    definition = snapshot.definition
    limits = definition.limits
    attempts = snapshot.attempts
    if definition.run_id != run_id or snapshot.scope != _SCOPE or snapshot.state not in {"ready", "running", "interrupted", "collected"}:
        raise ValueError
    if not _integer(snapshot.reserved_request_bytes, 0, definition.max_total_request_bytes) or not _integer(snapshot.reserved_response_bytes, 0, definition.max_total_response_bytes):
        raise ValueError
    previous = 0
    for attempt in attempts:
        if not _integer(attempt.ordinal, previous + 1, limits.request_count) or type(attempt.sample_index) is not int or attempt.sample_index != (attempt.ordinal - 1) % definition.input_count:
            raise ValueError
        previous = attempt.ordinal
        if not _integer(attempt.request_bytes, 1, 262144) or attempt.state not in {"dispatched", "observed", "delivery_unknown"}:
            raise ValueError
        status, size, elapsed = attempt.http_status, attempt.response_bytes, attempt.elapsed_ms
        if attempt.state == "dispatched":
            if any(value is not None for value in (attempt.kind, status, size, elapsed)):
                raise ValueError
            continue
        if attempt.kind not in _KINDS or (attempt.state == "delivery_unknown") != (attempt.kind == "delivery_unknown"):
            raise ValueError
        # Finalization can mark a dispatched ordinal unknown with no observation.
        if attempt.state == "delivery_unknown" and status is None and size is None and elapsed is None:
            continue
        success = type(status) is int and 200 <= status < 300
        if (
            (status is not None and not _integer(status, 100, 599))
            or not _integer(size, 0, limits.max_response_bytes + (attempt.kind in {"response_limit", "delivery_unknown"}))
            or type(elapsed) not in (int, float)
            or not math.isfinite(elapsed)
            or elapsed < 0
            or (attempt.kind in {"output_collected", "unsupported_response", "response_limit", "invalid_output"} and not success)
            or (attempt.kind == "http_error" and (status is None or success))
            or (attempt.kind in {"http_error", "unsupported_response", "policy_rejected"} and size != 0)
            or (attempt.kind == "policy_rejected" and status is not None)
            or (attempt.kind == "output_collected" and size == 0)
        ):
            raise ValueError
    if sum(item.request_bytes for item in attempts) != snapshot.reserved_request_bytes or len(attempts) * (limits.max_response_bytes + 1) != snapshot.reserved_response_bytes:
        raise ValueError
    if snapshot.state == "ready" and attempts:
        raise ValueError
    if snapshot.state in {"running", "collected"} and any(item.state == "delivery_unknown" for item in attempts):
        raise ValueError
    if snapshot.state == "collected" and (len(attempts) != limits.request_count or any(item.state != "observed" for item in attempts)):
        raise ValueError


def reconcile(journal_path, run_id):
    """Take one consistent read-only snapshot of exactly the named local run.

    Frozen inputs/requests are always the denominators. A successful read and a
    terminal 'collected' state prove neither output fsync nor target delivery.
    Neither observed absence nor process death authorizes a new send.
    """
    reader = None
    try:
        if type(run_id) is not str or str(UUID(run_id)) != run_id:
            raise ValueError
        path = Path(journal_path).absolute()
        identity = _regular(path)
        for suffix in ("-wal", "-shm", "-journal"):
            _regular(Path(str(path) + suffix), optional=True)
        reader = LocalJSONJournal.open(path)
        snapshot = reader.snapshot()
        if identity != _regular(path):
            raise ValueError
        _validate(snapshot, run_id)
        definition = snapshot.definition
        states = Counter(item.state for item in snapshot.attempts)
        kinds = Counter(item.kind for item in snapshot.attempts if item.kind is not None)
        return {
            "schema": "local-qa-reconciliation.v1",
            "scope": _SCOPE,
            "verdict": "NOT_EVALUATED",
            "run_id": definition.run_id,
            "declared_source_sha256": definition.source_sha256,
            "state": snapshot.state,
            "frozen_input_count": definition.input_count,
            "frozen_request_count": definition.limits.request_count,
            "reserved_attempt_count": len(snapshot.attempts),
            "unreserved_in_snapshot_count": definition.limits.request_count - len(snapshot.attempts),
            "covered_input_count": len({item.sample_index for item in snapshot.attempts}),
            "attempt_states": {state: states[state] for state in ("dispatched", "observed", "delivery_unknown")},
            "observation_kinds": {kind: kinds[kind] for kind in sorted(_KINDS)},
            "reserved_request_bytes": snapshot.reserved_request_bytes,
            "reserved_response_bytes": snapshot.reserved_response_bytes,
            "output_content_verified": False,
            "platform_provenance_verified": False,
            "resend_permitted": False,
            "resume_permitted": False,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, LocalJournalUnconfirmed):
        raise ValueError("Local QA reconciliation unconfirmed; never retry or resend") from None
    finally:
        if reader is not None:
            reader.close()


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid reconciliation arguments")


def main(argv=None):
    parser = _Parser(description="OFFLINE same-ID journal metadata only. No outputs, resume, resend, import or approval.")
    parser.add_argument("--journal", required=True)
    parser.add_argument("--run-id", required=True)
    try:
        args = parser.parse_args(argv)
        print(json.dumps(reconcile(args.journal, args.run_id), sort_keys=True))
        return 0  # Read succeeded; not run success, PASS or approval.
    except KeyboardInterrupt:
        print("Local QA reconciliation cancelled. Retain the original journal; never resend.", file=sys.stderr)
        return 130
    except Exception:
        print("Local QA reconciliation unconfirmed. Retain the original journal; never resend.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
