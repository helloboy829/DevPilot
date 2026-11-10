"""Private one-shot local journal and adapter for the shared bounded JSON core.

Technical metadata only; no plaintext request/input/output hashes or values.
Not admission, platform provenance, a global quota, a resumable CLI or approval.
Use a trusted local directory/filesystem. Reopened files are read-only: neither
an expired deadline nor process death grants a new claim or permission to resend.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from devpilot.qa_json_attempt import AttemptObservation
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_run import JSONRunLimits, run_json_attempts
from devpilot.request_versions import FrozenRequest

_SCHEMA = "local-qa-json-journal.v1"
_MAX_TOTAL = 67_108_864


class LocalJournalConflict(Exception):
    """No permission to start, dispatch, record or resume this local run."""


class LocalJournalUnconfirmed(Exception):
    """An operation was not confirmed. Read only; NEVER infer permission to send."""


def _integer(value, lower, upper):
    return type(value) is int and lower <= value <= upper


def _time(value):
    if not _integer(value, 1, 9_007_199_254_740_991):
        raise ValueError("Invalid local clock")
    return value


@dataclass(frozen=True, slots=True)
class LocalRunDefinition:
    run_id: str
    source_sha256: str
    input_count: int
    limits: JSONRunLimits
    max_total_request_bytes: int
    max_total_response_bytes: int

    def __post_init__(self):
        try:
            if (
                type(self.run_id) is not str
                or str(UUID(self.run_id)) != self.run_id
                or type(self.source_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
                or not isinstance(self.limits, JSONRunLimits)
                or not _integer(self.limits.deadline_ms, 1, 9_007_199_254_740_991)
                or not _integer(self.input_count, 1, min(500, self.limits.request_count))
                or not _integer(self.max_total_request_bytes, 1, _MAX_TOTAL)
                or not _integer(self.max_total_response_bytes, self.limits.max_response_bytes + 1, _MAX_TOTAL)
            ):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid local run definition") from None


@dataclass(frozen=True, slots=True)
class LocalDispatchTicket:
    run_id: str
    ordinal: int
    sample_index: int
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LocalAttemptSnapshot:
    ordinal: int
    sample_index: int
    request_bytes: int
    state: str
    kind: str | None
    http_status: int | None
    response_bytes: int | None
    elapsed_ms: float | None


@dataclass(frozen=True, slots=True)
class LocalRunSnapshot:
    definition: LocalRunDefinition
    state: str
    reserved_request_bytes: int
    reserved_response_bytes: int
    attempts: tuple[LocalAttemptSnapshot, ...]
    scope: str = "external_unverified_technical_only"


class LocalJSONJournal:
    """One private file per run; only the original create result can mutate it.

    SQLite FULL synchronous commit must return before a ticket is returned.
    Durability still depends on a functioning local filesystem/storage stack;
    this is not protection against a malicious file owner, replacement/rollback,
    network filesystems or a remote exactly-once business-operation guarantee.
    No transaction stays open across a network or output callback. One idle
    anchor prevents last-connection WAL cleanup racing read-only reconciliation.
    """

    def __init__(self, path, *, _token=None):
        self._path = Path(path).absolute()
        self._token = _token
        self._lock = threading.Lock()
        self._anchor = None

    @classmethod
    def open(cls, path):
        """Read-only reconciliation. Does not create, claim, recover or migrate."""
        return cls(path)

    @classmethod
    def create(cls, path, definition: LocalRunDefinition):
        if not isinstance(definition, LocalRunDefinition):
            raise ValueError("Invalid local run definition")
        definition = LocalRunDefinition(**{name: getattr(definition, name) for name in definition.__dataclass_fields__})
        owned = cls(path, _token=secrets.token_hex(32))
        try:
            descriptor = os.open(owned._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        except FileExistsError:
            raise LocalJournalConflict("Local run already exists") from None
        except OSError:
            raise LocalJournalUnconfirmed("Local journal operation unconfirmed") from None
        # Leave any ambiguous file in place. Never delete/recreate it or retry.
        with owned._connection(write=True, initialize=True) as db:
            db.execute(
                "CREATE TABLE local_run (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema TEXT NOT NULL, "
                "definition TEXT NOT NULL, claim_hash TEXT NOT NULL, state TEXT NOT NULL, request_bytes INTEGER NOT NULL, response_bytes INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE local_attempts (ordinal INTEGER PRIMARY KEY, sample_index INTEGER NOT NULL, request_bytes INTEGER NOT NULL, "
                "ticket_hash TEXT NOT NULL, state TEXT NOT NULL, kind TEXT, http_status INTEGER, response_bytes INTEGER, elapsed_ms REAL)"
            )
            payload = {
                "run_id": definition.run_id,
                "source_sha256": definition.source_sha256,
                "input_count": definition.input_count,
                "limits": {name: getattr(definition.limits, name) for name in definition.limits.__dataclass_fields__},
                "max_total_request_bytes": definition.max_total_request_bytes,
                "max_total_response_bytes": definition.max_total_response_bytes,
            }
            import json

            db.execute("INSERT INTO local_run VALUES (1, ?, ?, ?, 'ready', 0, 0)", (_SCHEMA, json.dumps(payload, sort_keys=True, separators=(",", ":")), owned._hash(owned._token)))
        return owned

    @staticmethod
    def _hash(token):
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    @contextmanager
    def _connection(self, *, write=False, initialize=False):
        # Serialize this owner's off-loop reads AND writes without DB retries.
        # Separate processes/readers get immediate generic SQLite lock failure.
        with self._lock:
            if write and self._token is None:
                raise LocalJournalConflict("Local run unavailable")
            db = None
            try:
                db = sqlite3.connect(self._path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=0, isolation_level=None, check_same_thread=False)
                db.row_factory = sqlite3.Row
                if write:
                    if initialize:
                        if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                            raise LocalJournalUnconfirmed("Local journal operation unconfirmed")
                    db.execute("PRAGMA synchronous=FULL")
                    db.execute("BEGIN IMMEDIATE")
                else:
                    db.execute("PRAGMA query_only=ON")
                    db.execute("BEGIN")
                yield db
                db.commit()
                if initialize:
                    # Keep one idle connection until explicit close. Without it,
                    # last-connection WAL cleanup can race a newly opened reader.
                    # No transaction remains open and no retry is introduced.
                    self._anchor = db
            except (sqlite3.Error, OSError):
                raise LocalJournalUnconfirmed("Local journal operation unconfirmed") from None
            finally:
                if db is not None and db is not self._anchor:
                    db.close()

    def close(self):
        """Drain first; close the idle anchor and irreversibly drop this claim."""
        with self._lock:
            self._token = None
            if self._anchor is not None:
                try:
                    self._anchor.close()
                except sqlite3.Error:
                    raise LocalJournalUnconfirmed("Local journal operation unconfirmed") from None
                finally:
                    self._anchor = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _run(self, db, *, write=False):
        import json

        row = db.execute("SELECT * FROM local_run WHERE singleton=1").fetchone()
        if row is None or row["schema"] != _SCHEMA:
            raise LocalJournalUnconfirmed("Local journal operation unconfirmed")
        if write and (self._token is None or not hmac.compare_digest(row["claim_hash"], self._hash(self._token))):
            raise LocalJournalConflict("Local run unavailable")
        try:
            data = json.loads(row["definition"])
            data["limits"] = JSONRunLimits(**data["limits"])
            definition = LocalRunDefinition(**data)
        except (ValueError, TypeError, KeyError):
            raise LocalJournalUnconfirmed("Local journal operation unconfirmed") from None
        return row, definition

    def snapshot(self):
        with self._connection() as db:
            row, definition = self._run(db)
            attempts = db.execute("SELECT ordinal, sample_index, request_bytes, state, kind, http_status, response_bytes, elapsed_ms FROM local_attempts ORDER BY ordinal LIMIT 10001").fetchall()
            if len(attempts) > definition.limits.request_count:
                raise LocalJournalUnconfirmed("Local journal operation unconfirmed")
            return LocalRunSnapshot(definition, row["state"], row["request_bytes"], row["response_bytes"], tuple(LocalAttemptSnapshot(**dict(item)) for item in attempts))

    def start(self, now_ms):
        now_ms = _time(now_ms)
        with self._connection(write=True) as db:
            row, definition = self._run(db, write=True)
            if row["state"] != "ready" or now_ms >= definition.limits.deadline_ms:
                raise LocalJournalConflict("Local run unavailable")
            db.execute("UPDATE local_run SET state='running' WHERE singleton=1")

    def reserve(self, ordinal, body_bytes, now_ms):
        if not _integer(ordinal, 1, 10000) or not _integer(body_bytes, 1, 262144):
            raise ValueError("Invalid local dispatch")
        now_ms = _time(now_ms)
        token = secrets.token_hex(32)
        with self._connection(write=True) as db:
            row, definition = self._run(db, write=True)
            limits = definition.limits
            inflight = db.execute("SELECT count(*) FROM local_attempts WHERE state='dispatched'").fetchone()[0]
            if (
                row["state"] != "running"
                or now_ms >= limits.deadline_ms
                or db.execute("SELECT 1 FROM local_attempts WHERE ordinal=?", (ordinal,)).fetchone() is not None
                or ordinal > limits.request_count
                or inflight >= limits.concurrency
                or row["request_bytes"] + body_bytes > definition.max_total_request_bytes
                or row["response_bytes"] + limits.max_response_bytes + 1 > definition.max_total_response_bytes
            ):
                raise LocalJournalConflict("Local dispatch unavailable")
            sample_index = (ordinal - 1) % definition.input_count
            db.execute("INSERT INTO local_attempts (ordinal,sample_index,request_bytes,ticket_hash,state) VALUES (?,?,?,?,'dispatched')", (ordinal, sample_index, body_bytes, self._hash(token)))
            db.execute("UPDATE local_run SET request_bytes=request_bytes+?, response_bytes=response_bytes+? WHERE singleton=1", (body_bytes, limits.max_response_bytes + 1))
        # A commit exception NEVER returns the capability to send.
        return LocalDispatchTicket(definition.run_id, ordinal, sample_index, token)

    @staticmethod
    def _observation(value):
        kinds = {"output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output", "delivery_unknown", "policy_rejected"}
        if not isinstance(value, AttemptObservation) or type(value.kind) is not str or value.kind not in kinds:
            raise ValueError("Invalid local observation")
        status, size, elapsed = value.http_status, value.body_bytes, value.elapsed_ms
        success = type(status) is int and 200 <= status < 300
        if (
            (status is not None and not _integer(status, 100, 599))
            or not _integer(size, 0, 1048577)
            or type(elapsed) not in (float, int)
            or not math.isfinite(elapsed)
            or elapsed < 0
            or (value.kind in {"output_collected", "unsupported_response", "response_limit", "invalid_output"} and not success)
            or (value.kind == "http_error" and (status is None or success))
            or (value.kind in {"http_error", "unsupported_response", "policy_rejected"} and size != 0)
            or (value.kind == "policy_rejected" and status is not None)
            or (value.kind == "output_collected" and (size == 0 or type(value.output) is not str))
            or (value.kind != "output_collected" and value.output is not None)
        ):
            raise ValueError("Invalid local observation")

    def record(self, ticket, observation):
        self._observation(observation)
        if not isinstance(ticket, LocalDispatchTicket) or type(ticket.token) is not str or re.fullmatch(r"[0-9a-f]{64}", ticket.token) is None:
            raise LocalJournalConflict("Local observation unavailable")
        with self._connection(write=True) as db:
            row, definition = self._run(db, write=True)
            attempt = db.execute("SELECT * FROM local_attempts WHERE ordinal=?", (ticket.ordinal,)).fetchone()
            if (
                row["state"] not in {"running", "interrupted"}
                or ticket.run_id != definition.run_id
                or attempt is None
                or attempt["state"] != "dispatched"
                or type(ticket.ordinal) is not int
                or type(ticket.sample_index) is not int
                or ticket.sample_index != attempt["sample_index"]
                or not hmac.compare_digest(attempt["ticket_hash"], self._hash(ticket.token))
            ):
                raise LocalJournalConflict("Local observation unavailable")
            if observation.body_bytes > definition.limits.max_response_bytes + (observation.kind in {"response_limit", "delivery_unknown"}):
                raise ValueError("Invalid local observation")
            unknown = observation.kind == "delivery_unknown"
            db.execute(
                "UPDATE local_attempts SET state=?,kind=?,http_status=?,response_bytes=?,elapsed_ms=? WHERE ordinal=?",
                ("delivery_unknown" if unknown else "observed", observation.kind, observation.http_status, observation.body_bytes, observation.elapsed_ms, ticket.ordinal),
            )
            if unknown:
                db.execute("UPDATE local_run SET state='interrupted' WHERE singleton=1")

    def check_active(self, now_ms):
        now_ms = _time(now_ms)
        with self._connection() as db:
            row, definition = self._run(db, write=True)
            return row["state"] == "running" and now_ms < definition.limits.deadline_ms

    def finish(self, *, completed):
        if type(completed) is not bool:
            raise ValueError("Invalid local finalization")
        with self._connection(write=True) as db:
            row, definition = self._run(db, write=True)
            if row["state"] not in {"running", "interrupted"}:
                raise LocalJournalConflict("Local finalization unavailable")
            observed = db.execute("SELECT count(*) FROM local_attempts WHERE state='observed'").fetchone()[0]
            collected = completed and row["state"] == "running" and observed == definition.limits.request_count
            db.execute("UPDATE local_attempts SET state='delivery_unknown',kind='delivery_unknown' WHERE state='dispatched'")
            db.execute("UPDATE local_run SET state=? WHERE singleton=1", ("collected" if collected else "interrupted",))
        return self.snapshot()


async def _drained_database(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.done():
                raise
            cancelled = True
        except BaseException:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result


async def run_local_json_attempts(journal, request, binding, inputs, *, now_ms, collect_attempt, record_output, check_active):
    """Delegate the real shared loop; mandatory caller policy/output capabilities.

    No default network client or output persistence. Output is sensitive and never
    stored here; the explicit callback must enforce its own disclosure/storage
    policy. Returned technical metadata is external/unverified, NOT QA evidence.
    All local DB operations (including monitor reads) drain before finalization.
    Repeated cancellation cancels the inner run once and awaits its cleanup.
    """
    if not isinstance(journal, LocalJSONJournal) or not isinstance(request, FrozenRequest) or not isinstance(binding, QAJSONBinding):
        raise ValueError("Invalid local run input")
    if not all(callable(value) for value in (now_ms, collect_attempt, record_output, check_active)):
        raise ValueError("Invalid local run capabilities")
    if type(inputs) is not tuple or any(type(value) is not str for value in inputs):
        raise ValueError("Invalid local run input")

    async def execute():
        snapshot = await _drained_database(journal.snapshot)
        if len(inputs) != snapshot.definition.input_count:
            raise ValueError("Invalid local run input")
        # A failed/ambiguous start has no permission to dispatch or finalize.
        await _drained_database(journal.start, now_ms())

        async def reserve(ordinal, body_bytes):
            return await _drained_database(journal.reserve, ordinal, body_bytes, now_ms())

        async def record(ticket, result):
            await _drained_database(journal.record, ticket, result)
            await record_output(ticket, result)

        async def active():
            return await _drained_database(journal.check_active, now_ms()) and await check_active()

        try:
            await run_json_attempts(request, binding, inputs, snapshot.definition.limits, now_ms=now_ms, reserve_attempt=reserve, collect_attempt=collect_attempt, record_attempt=record, check_active=active)
        except BaseException as original:
            try:
                await _drained_database(journal.finish, completed=False)
            except BaseException as failure:
                raise original from failure
            raise
        return await _drained_database(journal.finish, completed=True)

    async def execute_and_close():
        try:
            return await execute()
        finally:
            await _drained_database(journal.close)

    task = asyncio.create_task(execute_and_close())
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            # If the inner task itself was cancelled, do not spin on a done task.
            if task.done():
                raise
            if not cancelled:
                task.cancel()
            cancelled = True
        except BaseException:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result
