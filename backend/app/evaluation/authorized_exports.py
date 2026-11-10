"""Explicit platform export authorization, not execution or formal approval.

Only value-free configuration and separately granted baseline inputs are supported.
The offline recipient must rebind ALL request values and independently authorize
network/output use. The platform cannot enforce modified off-platform software.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import os
import time
import zipfile
from typing import Literal
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from devpilot.local_qa_cli import LocalRunManifest
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_templates import RequestTemplate
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.plan_repository import PlanRepository, _verified_inputs
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError, RequestProtectionUnavailable

MAX_BUNDLE_BYTES = 5_242_880
EXPORTER = "platform-local-qa-config.v1"
MAX_ENCRYPTED_CHARACTERS = 15_000_000


class ExportUnavailable(Exception):
    """Operator grant is absent, expired or unavailable; never echo source data."""


def _identifier(value):
    if type(value) is not str or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid export identifier")
    return value


class ExportGrant(StrictDTO):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    owner_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipient_id: str
    tier: Literal["skeleton", "baseline_inputs"]
    target_origin: str
    off_platform_authorized: Literal[True]
    expires_at_ms: int = Field(ge=1, le=253_402_300_799_000)

    @field_validator("target_origin")
    @classmethod
    def approved_origin(cls, value):
        return RequestTemplate("POST", value, ()).origin

    @field_validator("off_platform_authorized", mode="before")
    @classmethod
    def explicit_off_platform(cls, value):
        if value is not True:
            raise ValueError("Explicit off-platform authorization required")
        return value

    @field_validator("recipient_id")
    @classmethod
    def canonical_recipient(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("Canonical recipient account UUID required")
        return value


class ExportPolicy(StrictDTO):
    enabled: bool = False
    software_archive_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    max_response_bytes: int = Field(default=65_536, ge=1, le=1_048_576)
    max_total_response_bytes: int = Field(default=67_108_864, ge=2, le=67_108_864)
    grants: list[ExportGrant] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def explicit_grants(self):
        if len({g.id for g in self.grants}) != len(self.grants) or (self.enabled and (not self.software_archive_sha256 or not self.grants)):
            raise ValueError("Enabled export requires pinned software and unique explicit grants")
        return self


class ExportCreate(StrictDTO):
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    grant_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    recipient_id: str
    tier: Literal["skeleton", "baseline_inputs"]
    confirmed: Literal[True]
    data_use_confirmed: Literal[True]
    external_controls_acknowledged: Literal[True]

    _recipient = field_validator("recipient_id")(ExportGrant.canonical_recipient.__func__)

    @field_validator("confirmed", "data_use_confirmed", "external_controls_acknowledged", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


class ExportReceipt(StrictDTO):
    schema_version: Literal["platform-qa-export-receipt.v1"] = Field(alias="schema")
    scope: Literal["authorized_external_configuration_only"]
    exporter: Literal["platform-local-qa-config.v1"]
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    grant: ExportGrant
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipient_id: str
    tier: Literal["skeleton", "baseline_inputs"]
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    dataset_revision: int = Field(ge=1)
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_version_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    request_protected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_plan_schema: Literal["qa-json-plan.v1", "qa-json-plan.v2"]
    all_frozen_samples: int = Field(ge=1, le=500)
    manifest_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    software_archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sealed_bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_bytes: int = Field(ge=1, le=MAX_BUNDLE_BYTES)
    created_at_ms: int = Field(ge=1)
    input_set_complete: bool
    ready_for_preflight: Literal[False]
    request_values_included: Literal[False]
    reference_answers_included: Literal[False]
    execution_authorized: Literal[False]
    approval: Literal[False]
    verdict: Literal["NOT_EVALUATED"]

    @model_validator(mode="after")
    def coherent(self):
        g = self.grant
        if any(getattr(self, key) != getattr(g, key) for key in ("project_id", "plan_id", "plan_hash", "recipient_id", "tier")) or self.created_at_ms >= g.expires_at_ms or self.input_set_complete != (self.tier == "baseline_inputs"):
            raise ValueError("Invalid export receipt")
        return self


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _sealed_hash(token):
    try:
        if type(token) is not str or not 0 < len(token) <= MAX_ENCRYPTED_CHARACTERS:
            raise ValueError
        return _sha(token.encode("ascii"))
    except (ValueError, UnicodeError):
        raise RequestProtectionError("Export package failed integrity checks") from None


class ExportProtection:
    """Separate authenticated domain; no fallback, generated key or raw ZIP storage."""

    def __init__(self, key):
        try:
            self._cipher = Fernet(key)
        except (ValueError, TypeError):
            raise RequestProtectionUnavailable("Export protection key is missing or invalid") from None

    @classmethod
    def from_environment(cls):
        try:
            key = os.environ["DEVPILOT_REQUEST_ENCRYPTION_KEY"].encode("ascii")
        except (KeyError, UnicodeError):
            raise RequestProtectionUnavailable("Export protection key is missing or invalid") from None
        return cls(key)

    @staticmethod
    def _context(context):
        if type(context) is not dict or set(context) != {"owner_id", "project_id", "export_id", "plan_hash", "grant_hash"} or any(type(v) is not str or not 1 <= len(v) <= 64 for v in context.values()):
            raise RequestProtectionError("Invalid export protection context")
        return dict(context)

    def seal(self, bundle, context):
        if type(bundle) is not bytes or not 0 < len(bundle) <= MAX_BUNDLE_BYTES:
            raise RequestProtectionError("Export package rejected")
        envelope = _json({"schema": "protected-platform-qa-export.v1", "binding": self._context(context), "bundle_sha256": _sha(bundle), "bundle_hex": bundle.hex()})
        return self._cipher.encrypt(envelope).decode("ascii")

    def open(self, token, context):
        failed = False
        try:
            if type(token) is not str or not 0 < len(token) <= MAX_ENCRYPTED_CHARACTERS:
                raise ValueError
            envelope = json.loads(self._cipher.decrypt(token.encode("ascii")))
            if type(envelope) is not dict or set(envelope) != {"schema", "binding", "bundle_sha256", "bundle_hex"} or envelope["schema"] != "protected-platform-qa-export.v1" or envelope["binding"] != self._context(context):
                raise ValueError
            bundle = bytes.fromhex(envelope["bundle_hex"])
            if not 0 < len(bundle) <= MAX_BUNDLE_BYTES or not hmac.compare_digest(_sha(bundle), envelope["bundle_sha256"]):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, InvalidToken):
            failed = True
        # Do not retain JSONDecodeError.doc / decrypted data in exception context.
        if failed:
            raise RequestProtectionError("Export package cannot be opened or failed integrity checks")
        return bundle


_README_EN = """# Authorized local QA configuration - NOT APPROVED

This package contains configuration, not the independent software distribution.
Obtain the separately trusted software archive with the exact SHA256 in export.json.
Use its hash-locked offline installation into a fresh Python 3.12 venv; Linux is
verified synthetically, not Windows or real-target acceptance. Do not import a
working checkout or use an unpinned/system-site fallback.

Copy values.example.json to values.json and explicitly supply ALL request values
(URL including path/query, body and header values) on the recipient's machine.
No credentials, reference answers, historical outputs or local paths are exported.
Confirm target authorization, enterprise CA/TLS and approved hosts independently.
Never disable TLS validation. Input use is limited to the recorded recipient and
execute-only purpose. Do not redistribute inputs or use them for training.

Default dry-run: python -m devpilot.local_qa_cli --manifest manifest.json --values
values.json --inputs inputs.json (put this command on one line). It sends nothing.
A real send additionally requires the local CLI's explicit execute, fingerprint,
input-use, private-plaintext-output and host-policy confirmations; consult the
pinned software guide. Results go only to a fresh private directory and remain
external/unverified / NOT_EVALUATED. Missing evidence is not PASS. Never retry,
resume or resend uncertain delivery; inspect the original run ID with the pinned
read-only reconciliation command. Do not upload local databases or secrets.

The platform cannot enforce edited offline code, destinations or load limits.
Hashes are integrity checks, NOT signatures, output provenance or formal approval.
A fresh export ID records a new authorization; an uncertain PUT is reconciled only
by GET of the original ID, including after a 404. Never automatically resend PUT.
"""
_README_ZH = """# 平台授权本地 QA 配置包 — 未批准

此包不含运行软件。请取得 export.json 指定 SHA256 的独立软件包，按其锁定依赖说明
在全新 Python 3.12 虚拟环境中离线安装；Linux 合成验证不等于 Windows 或真实目标验收。
复制 values.example.json 为 values.json，在接收方机器上显式填写 URL、请求体和所有请求头值。
包内没有凭据、参考答案、历史响应或机器路径；输入仅限指定接收方的 execute-only 用途，
不能再分发或用于训练。独立确认目标授权、企业 CA/TLS 与主机策略，不得关闭 TLS 校验。

默认离线预检：python -m devpilot.local_qa_cli --manifest manifest.json --values values.json --inputs inputs.json
实发还须本地命令要求的执行、指纹、输入使用、私有明文结果和主机策略确认，详见锁定软件说明。
结果必须保存在全新私有目录，始终 external/unverified / NOT_EVALUATED，不是通过或批准。
未知交付不能重试、续跑或重发；仅以原运行 ID 显式只读对账。不要上传数据库或凭据。
平台无法持续约束被修改的离线代码、网络或负载；hash 不是签名或结果真实性证明。
未知 PUT 仅 GET 原导出 ID 对账，404 也不能自动重发。新导出需要新的独立授权确认。
"""


def _build_bundle(snapshot, payload, export_id, grant, policy):
    # All source validation, including template parsing, stays private and off-loop.
    try:
        return _build_bundle_checked(snapshot, payload, export_id, grant, policy)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise Conflict from None


def _build_bundle_checked(snapshot, payload, export_id, grant, policy):
    """Bounded deterministic package, using the REAL existing local CLI schema."""
    plan, version, dataset = (snapshot[n] for n in ("plan", "version", "dataset"))
    definition = plan["definition"]
    template = RequestTemplate.from_dict(version["request_template"])
    if (
        plan["definition_hash"] != payload.plan_hash
        or dataset["status"] != "frozen"
        or dataset["revision"] != definition["dataset_revision"]
        or dataset["content_hash"] != definition["dataset_hash"]
        or dataset["purpose"] != definition["dataset_purpose"]
        or dataset["sample_count"] != definition["preflight"]["sample_count"]
        or version["component_id"] != plan["component_id"]
        or version["scope"] != "request_definition_only"
        or version["protected_hash"] != definition["request_protected_hash"]
        or template.fingerprint != definition["request_template_fingerprint"]
        or definition["limits"]["mode"] != "effectiveness"
        or (payload.tier == "baseline_inputs" and dataset["purpose"] != "baseline")
    ):
        raise Conflict
    if grant.target_origin != template.origin:
        raise Conflict
    inputs = _verified_inputs(dataset, snapshot["samples"]) if payload.tier == "baseline_inputs" else ()
    limits = definition["limits"]
    manifest = LocalRunManifest(
        template=template,
        binding=QAJSONBinding.from_dict(definition["binding"]),
        input_count=dataset["sample_count"],
        request_count=limits["request_count"],
        concurrency=limits["concurrency"],
        timeout_ms=limits["timeout_ms"],
        duration_ms=limits["wall_time_ms"],
        max_response_bytes=policy.max_response_bytes,
        max_total_request_bytes=limits["max_total_body_bytes"],
        max_total_response_bytes=policy.max_total_response_bytes,
    )
    if manifest.request_count * (manifest.max_response_bytes + 1) > manifest.max_total_response_bytes:
        raise ValueError
    wiring = template.to_dict()
    refs = [wiring["url_ref"], wiring["body_ref"], *(ref for _, ref in wiring["headers"])]
    files = {
        "manifest.json": _json(manifest.to_dict()),
        "values.example.json": _json({"schema": "local-qa-values.v1", "bindings": {ref: "" for ref in refs}}),
        "inputs.json": _json({"schema": "local-qa-inputs.v1", "inputs": list(inputs)}),
        "README.en.md": (_README_EN + ("\nINCOMPLETE: supply authorized inputs; this skeleton cannot complete evaluation.\n" if payload.tier == "skeleton" else "")).encode("utf-8"),
        "README.zh.md": (_README_ZH + ("\n未完成：需自行提供获准输入，此骨架尚不能完成评测。\n" if payload.tier == "skeleton" else "")).encode("utf-8"),
    }
    if len(files["manifest.json"]) > 32_768 or len(files["values.example.json"]) > 524_288 or len(files["inputs.json"]) > 4_194_304:
        raise ValueError
    package = {
        "schema": "platform-qa-config-bundle.v1",
        "exporter": EXPORTER,
        "export_id": export_id,
        "plan_id": plan["id"],
        "plan_hash": plan["definition_hash"],
        "source_plan_schema": definition["schema"],
        "dataset_id": dataset["id"],
        "dataset_revision": dataset["revision"],
        "dataset_hash": dataset["content_hash"],
        "request_version_id": version["id"],
        "request_protected_hash": version["protected_hash"],
        "all_frozen_samples": manifest.input_count,
        "manifest_fingerprint": manifest.fingerprint,
        "grant": grant.model_dump(),
        "software_archive_sha256": policy.software_archive_sha256,
        "policy_hash": fingerprint(policy.model_dump(exclude={"grants", "enabled"})),
        "input_set_complete": payload.tier == "baseline_inputs",
        "ready_for_preflight": False,
        "mode": "execute_only",
        "criteria_evaluated": False,
        "verdict": "NOT_EVALUATED",
        "files": {name: _sha(data) for name, data in sorted(files.items())},
    }
    files["export.json"] = _json(package)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    bundle = output.getvalue()
    if len(bundle) > MAX_BUNDLE_BYTES:
        raise ValueError
    return bundle, package


async def _drain(operation):
    """Drain ALL DB reads/writes and off-loop work, then preserve cancellation."""
    task = asyncio.create_task(operation)
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
        except BaseException:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result


class ExportRepository(PlanRepository):
    _metadata = tuple(c for c in t.exports.c if c.name != "encrypted_bundle")

    def __init__(self, sf, *, policy=None, protection=None, clock_ms=None):
        super().__init__(sf)
        self._policy = ExportPolicy.model_validate((policy.model_dump() if isinstance(policy, ExportPolicy) else policy) or {})
        self._export_protection = protection
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def _protection(self):
        return self._export_protection or ExportProtection.from_environment()

    def _grant(self, owner, project_id, payload):
        policy = self._policy
        if not policy.enabled:
            raise ExportUnavailable
        for grant in policy.grants:
            if grant.id == payload.grant_id and all(
                getattr(grant, n) == value for n, value in {"owner_id": owner, "project_id": project_id, "plan_id": payload.plan_id, "plan_hash": payload.plan_hash, "recipient_id": payload.recipient_id, "tier": payload.tier}.items()
            ):
                if self.clock_ms() >= grant.expires_at_ms:
                    raise ExportUnavailable
                return grant.model_copy(deep=True)
        raise ExportUnavailable

    @staticmethod
    def _binding(owner, export_id, project_id, payload, grant):
        return {"owner_id": owner, "project_id": project_id, "export_id": export_id, "plan_hash": payload.plan_hash, "grant_hash": fingerprint(grant.model_dump())}

    async def _snapshot(self, session, owner, project_id, payload):
        project = await self._project(session, owner, project_id)
        plan = await self._plan(session, owner, project_id, payload.plan_id)
        definition = plan["definition"]
        await self._linked_component(session, owner, project_id, plan["component_id"])
        version = await self._request_version(session, owner, project_id, plan["request_version_id"])
        dataset = await self._dataset(session, owner, project_id, plan["dataset_id"])
        samples = []
        if payload.tier == "baseline_inputs":
            if dataset["purpose"] != "baseline":
                raise Conflict
            samples = [
                dict(row)
                for row in (
                    await session.execute(
                        select(t.samples.c.sample_id, t.samples.c.input, t.samples.c.source_ref, t.samples.c.slice_tag, t.references.c.expected)
                        .outerjoin(t.references, (t.samples.c.dataset_id == t.references.c.dataset_id) & (t.samples.c.sample_id == t.references.c.sample_id))
                        .where(t.samples.c.dataset_id == dataset["id"])
                        .order_by(t.samples.c.sample_id)
                        .limit(501)
                    )
                ).mappings()
            ]
        if plan["definition_hash"] != payload.plan_hash or definition["request_version_id"] != version["id"]:
            raise Conflict
        return {"project": project, "plan": plan, "version": version, "dataset": dataset, "samples": samples}

    async def _row(self, session, owner, project_id, export_id, *, sensitive=False):
        await self._project(session, owner, project_id)
        row = (await session.execute((select(t.exports) if sensitive else select(*self._metadata)).where(t.exports.c.id == export_id, t.exports.c.project_id == project_id, t.exports.c.owner_id == owner))).mappings().first()
        return dict(row) if row is not None else None

    @staticmethod
    def _decode(row):
        failed = False
        try:
            doc = ExportReceipt.model_validate(row["document"]).model_dump(by_alias=True)
            if (
                doc != row["document"]
                or any(row[n] != doc[n] for n in ("id", "project_id", "plan_id", "created_at_ms"))
                or doc["grant"]["owner_id"] != row["owner_id"]
                or not hmac.compare_digest(row["receipt_hash"], fingerprint({"owner_id": row["owner_id"], "request_hash": row["request_hash"], "document": doc}))
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError, AttributeError):
            failed = True
        if failed:
            raise RequestProtectionError("Export receipt failed integrity checks")
        return {**doc, "receipt_hash": row["receipt_hash"]}

    async def create(self, owner, project_id, export_id, payload):
        _identifier(export_id)
        payload = ExportCreate.model_validate(payload.model_dump())
        return await _drain(self._create(owner, project_id, export_id, payload))

    async def _create(self, owner, project_id, export_id, payload):
        async with self.sf() as session:
            if await self._row(session, owner, project_id, export_id):
                raise Conflict  # Receipt inspection is GET-only, never a repeated PUT.
            grant = self._grant(owner, project_id, payload)
            snapshot = await self._snapshot(session, owner, project_id, payload)
        policy = self._policy.model_copy(deep=True)
        bundle, package = await asyncio.to_thread(_build_bundle, snapshot, payload, export_id, grant, policy)
        context = self._binding(owner, export_id, project_id, payload, grant)
        token = await asyncio.to_thread(self._protection().seal, bundle, context)
        self._grant(owner, project_id, payload)
        created_at = self.clock_ms()
        if created_at >= grant.expires_at_ms:
            raise ExportUnavailable
        document = ExportReceipt.model_validate(
            {
                "schema": "platform-qa-export-receipt.v1",
                "scope": "authorized_external_configuration_only",
                "exporter": EXPORTER,
                "id": export_id,
                "project_id": project_id,
                "plan_id": payload.plan_id,
                "plan_hash": payload.plan_hash,
                "grant": grant.model_dump(),
                "recipient_id": payload.recipient_id,
                "tier": payload.tier,
                **{
                    n: package[n]
                    for n in (
                        "policy_hash",
                        "dataset_id",
                        "dataset_revision",
                        "dataset_hash",
                        "request_version_id",
                        "request_protected_hash",
                        "source_plan_schema",
                        "all_frozen_samples",
                        "manifest_fingerprint",
                        "software_archive_sha256",
                        "input_set_complete",
                        "ready_for_preflight",
                    )
                },
                "sealed_bundle_hash": await asyncio.to_thread(_sealed_hash, token),
                "bundle_bytes": len(bundle),
                "created_at_ms": created_at,
                "request_values_included": False,
                "reference_answers_included": False,
                "execution_authorized": False,
                "approval": False,
                "verdict": "NOT_EVALUATED",
            }
        ).model_dump(by_alias=True)
        request_hash = fingerprint(payload.model_dump())
        row = {n: document[n] for n in ("id", "project_id", "plan_id", "created_at_ms")}
        row.update(owner_id=owner, request_hash=request_hash, document=document, encrypted_bundle=token, receipt_hash=fingerprint({"owner_id": owner, "request_hash": request_hash, "document": document}))
        try:
            async with self.sf.begin() as session:
                locked = (await session.execute(update(t.projects).where(t.projects.c.id == project_id, t.projects.c.owner_id == owner).values(id=t.projects.c.id).returning(t.projects))).mappings().first()
                if locked is None:
                    raise NotFound
                # Sources are immutable via normal APIs; also fence unexpected direct changes.
                if dict(locked) != snapshot["project"] or snapshot != await self._snapshot(session, owner, project_id, payload):
                    raise Conflict
                if self._grant(owner, project_id, payload) != grant or await self._row(session, owner, project_id, export_id):
                    raise Conflict
                await session.execute(insert(t.exports).values(**row))
                await self._event(session, owner, project_id, export_id, "export_created")
        except IntegrityError:
            raise Conflict from None
        return self._decode(row)

    async def get(self, owner, project_id, export_id):
        _identifier(export_id)
        return await _drain(self._get(owner, project_id, export_id))

    async def _get(self, owner, project_id, export_id):
        async with self.sf() as session:
            row = await self._row(session, owner, project_id, export_id)
        if row is None:
            raise NotFound
        return await asyncio.to_thread(self._decode, row)

    async def open_bundle(self, owner, project_id, export_id, viewed_receipt_hash):
        _identifier(export_id)
        return await _drain(self._open_bundle(owner, project_id, export_id, viewed_receipt_hash))

    async def _open_bundle(self, owner, project_id, export_id, viewed_receipt_hash):
        async with self.sf() as session:
            row = await self._row(session, owner, project_id, export_id, sensitive=True)
        if row is None:
            raise NotFound
        receipt = await asyncio.to_thread(self._decode, row)
        if type(viewed_receipt_hash) is not str or not hmac.compare_digest(receipt["receipt_hash"], viewed_receipt_hash):
            raise Conflict
        grant = ExportGrant.model_validate(receipt["grant"])
        payload = ExportCreate(
            plan_id=receipt["plan_id"], plan_hash=receipt["plan_hash"], grant_id=grant.id, recipient_id=receipt["recipient_id"], tier=receipt["tier"], confirmed=True, data_use_confirmed=True, external_controls_acknowledged=True
        )
        if self._grant(owner, project_id, payload) != grant or self._policy.software_archive_sha256 != receipt["software_archive_sha256"] or fingerprint(self._policy.model_dump(exclude={"grants", "enabled"})) != receipt["policy_hash"]:
            raise ExportUnavailable
        if not hmac.compare_digest(await asyncio.to_thread(_sealed_hash, row["encrypted_bundle"]), receipt["sealed_bundle_hash"]):
            raise RequestProtectionError("Export package failed integrity checks")
        bundle = await asyncio.to_thread(self._protection().open, row["encrypted_bundle"], self._binding(owner, export_id, project_id, payload, grant))
        if len(bundle) != receipt["bundle_bytes"]:
            raise RequestProtectionError("Export package failed integrity checks")
        async with self.sf.begin() as session:
            locked = (await session.execute(update(t.projects).where(t.projects.c.id == project_id, t.projects.c.owner_id == owner).values(id=t.projects.c.id).returning(t.projects.c.id))).first()
            if locked is None:
                raise NotFound
            if self._grant(owner, project_id, payload) != grant or row != await self._row(session, owner, project_id, export_id, sensitive=True):
                raise Conflict
            await self._event(session, owner, project_id, export_id, "bundle_opened")
        return bundle

    async def _event(self, session, owner, project_id, export_id, action):
        # Every caller holds the project lock; timestamps never define audit order.
        sequence = (await session.scalar(select(func.max(t.export_audit.c.sequence)).where(t.export_audit.c.export_id == export_id))) or 0
        await session.execute(insert(t.export_audit).values(id=uuid4().hex, project_id=project_id, export_id=export_id, actor=owner, action=action, sequence=sequence + 1, at_ms=self.clock_ms()))

    async def audit(self, owner, project_id, export_id, *, after_sequence=0, limit=100):
        _identifier(export_id)
        if type(after_sequence) is not int or not 0 <= after_sequence <= 2_147_483_647 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid audit page")
        return await _drain(self._audit_events(owner, project_id, export_id, after_sequence, limit))

    async def _audit_events(self, owner, project_id, export_id, after_sequence, limit):
        async with self.sf() as session:
            if await self._row(session, owner, project_id, export_id) is None:
                raise NotFound
            return [
                dict(r)
                for r in (
                    await session.execute(
                        select(t.export_audit).where(t.export_audit.c.project_id == project_id, t.export_audit.c.export_id == export_id, t.export_audit.c.sequence > after_sequence).order_by(t.export_audit.c.sequence).limit(limit)
                    )
                ).mappings()
            ]
