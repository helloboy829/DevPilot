"""Immutable owner-scoped QA report drafts from reverified platform summaries.

No supplied metrics, Q/A, model calls, publication or automatic acceptance.
Templates and rendered Markdown are frozen with each append-only report revision.
"""

from __future__ import annotations

import asyncio
import copy
import hmac
import html
from typing import Literal

from pydantic import Field, field_validator
from sqlalchemy import insert, select, update

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError


class ArchiveSource(StrictDTO):
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    summary_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArchiveCreate(StrictDTO):
    title: str = Field(min_length=1, max_length=160)
    template_id: str = Field(min_length=1, max_length=64)
    template_version: str = Field(min_length=1, max_length=32)
    sources: list[ArchiveSource] = Field(min_length=1, max_length=10)
    supersedes_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value

    @field_validator("sources")
    @classmethod
    def unique_sorted_sources(cls, value):
        if len({item.run_id for item in value}) != len(value):
            raise ValueError("Duplicate run")
        return sorted(value, key=lambda item: item.run_id)

    @field_validator("title")
    @classmethod
    def unicode_title(cls, value):
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid report title") from None
        return value


def archive_templates():
    return [
        {
            "id": "verified-qa-project-en",
            "version": "1.0.0",
            "language": "en",
            "layout": {
                "heading": "Project QA evaluation report — DRAFT / NOT APPROVED",
                "project": "Project",
                "notice": (
                    "Historical platform evidence, not publication or project acceptance. Latest human PASS / ALL frozen samples. "
                    "No pooled cross-component rate, performance metrics or automatic PASS. Later reviews and templates do not rewrite this archive."
                ),
                "columns": "Component | Frozen plan | Human PASS / All samples | Human pass rate",
                "sources": "Frozen evidence references",
                "footer": "Each component retains its independent run, plan and evidence-bound summary identifiers. A revision creates a new archive; it does not modify this record.",
            },
        },
        {
            "id": "verified-qa-project-zh",
            "version": "1.0.0",
            "language": "zh",
            "layout": {
                "heading": "项目 QA 评测报告 — 草稿 / 未批准（DRAFT）",
                "project": "项目",
                "notice": "这是历史平台证据草稿，不是正式出具或项目验收。人工通过率＝最新人工通过数 / 全部冻结样本；不跨组件平均，不混入性能指标，不自动判定通过。后续复核和模板更新不改写本存档。",
                "columns": "组件 | 冻结计划 | 人工通过数 / 全部样本 | 人工通过率",
                "sources": "冻结证据引用",
                "footer": "每个组件独立保留运行、计划及证据绑定的汇总标识。修订创建新的存档，不覆盖本记录。",
            },
        },
    ]


def _safe(text):
    text = html.escape(str(text)).replace("\r", " ").replace("\n", " ")
    for char in ("\\", "|", "`", "*", "_", "[", "]", "#", "!"):
        text = text.replace(char, "&#" + str(ord(char)) + ";")
    return text


def _render(title, project, template, summaries):
    layout = template["layout"]
    lines = ["# " + layout["heading"], "", "## " + _safe(title), "", layout["project"] + ": " + _safe(project["name"]), "", layout["notice"], "", "| " + layout["columns"] + " |", "| --- | --- | ---: | ---: |"]
    for item in summaries:
        rate = item["human_pass_rate"]
        lines.append("| " + " | ".join([_safe(item["component_name"]), _safe(item["plan_label"]), str(rate["numerator"]) + " / " + str(rate["denominator"]), f"{rate['value']:.2%}"]) + " |")
    lines.extend(["", "## " + layout["sources"], ""])
    for item in summaries:
        lines.extend(["- " + _safe(item["component_name"]), "  - Run: " + _safe(item["run_id"]), "  - Plan: " + _safe(item["plan_hash"]), "  - Summary: " + _safe(item["summary_hash"])])
    lines.extend(["", layout["footer"], "", "Template: " + _safe(template["id"]) + "@" + _safe(template["version"])])
    return "\n".join(lines)


class ReportArchiveRepository(SummaryRepository):
    @staticmethod
    def _identifier(value):
        if not isinstance(value, str) or len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("Invalid report identifier")

    async def _archive_row(self, session, owner, project_id, archive_id):
        await self._project(session, owner, project_id)
        row = (await session.execute(select(t.report_archives).where(t.report_archives.c.id == archive_id, t.report_archives.c.project_id == project_id, t.report_archives.c.owner_id == owner))).mappings().first()
        return dict(row) if row is not None else None

    @staticmethod
    def _decode(row):
        try:
            doc = row["document"]
            if not hmac.compare_digest(fingerprint({"owner_id": row["owner_id"], "request_hash": row["request_hash"], "document": doc}), row["archive_hash"]):
                raise ValueError
            if doc["schema"] != "qa-project-report-archive.v1" or doc["acceptance"] != "not_approved" or doc["scope"] != "immutable_qa_report_draft":
                raise ValueError
            if any(doc[key] != row[key] for key in ("id", "project_id", "root_id", "revision", "supersedes_id", "title", "created_at_ms")):
                raise ValueError
            if (doc["template"]["id"], doc["template"]["version"]) != (row["template_id"], row["template_version"]):
                raise ValueError
            return {**doc, "archive_hash": row["archive_hash"]}
        except (ValueError, TypeError, KeyError, AttributeError):
            raise RequestProtectionError("Report archive integrity check failed") from None

    async def get_archive(self, owner, project_id, archive_id):
        self._identifier(archive_id)
        async with self.sf() as session:
            row = await self._archive_row(session, owner, project_id, archive_id)
        if row is None:
            raise NotFound
        return await asyncio.to_thread(self._decode, row)

    async def list_archives(self, owner, project_id):
        # Metadata only. Explicit open validates the stored document and receipt.
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            columns = [c for c in t.report_archives.c if c.name not in {"document", "owner_id", "request_hash", "archive_hash"}]
            rows = (
                await session.execute(select(*columns).where(t.report_archives.c.project_id == project_id, t.report_archives.c.owner_id == owner).order_by(t.report_archives.c.created_at_ms.desc(), t.report_archives.c.id.desc()).limit(100))
            ).mappings()
            return [dict(row) for row in rows]

    @staticmethod
    def _verify_sources(owner, snapshots, protection):
        summaries = [SummaryRepository._verify_summary(owner, source, protection) for source in snapshots]
        if any(item["readiness"] != "review_complete" or item["blockers"] for item in summaries) or len({item["component_id"] for item in summaries}) != len(summaries):
            raise Conflict
        return sorted(summaries, key=lambda item: item["component_id"])

    async def create_archive(self, owner, project_id, archive_id, payload: ArchiveCreate):
        self._identifier(archive_id)
        payload = ArchiveCreate.model_validate(payload.model_dump())
        request_hash = fingerprint(payload.model_dump())
        async with self.sf() as session:
            project = await self._project(session, owner, project_id)
            existing = await self._archive_row(session, owner, project_id, archive_id)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return await asyncio.to_thread(self._decode, existing)
            parent = await self._archive_row(session, owner, project_id, payload.supersedes_id) if payload.supersedes_id else None
            if payload.supersedes_id and parent is None:
                raise NotFound
            previous = await asyncio.to_thread(self._decode, parent) if parent else None
            template = next((copy.deepcopy(item) for item in archive_templates() if (item["id"], item["version"]) == (payload.template_id, payload.template_version)), None)
            if template is None:
                raise Conflict
            snapshots = [await self._summary_snapshot(session, owner, project_id, source.run_id) for source in payload.sources]
        summaries = await asyncio.to_thread(self._verify_sources, owner, snapshots, self._evidence_protection())
        if {item["run_id"]: item["summary_hash"] for item in summaries} != {item.run_id: item.summary_hash for item in payload.sources}:
            raise Conflict
        document = {
            "schema": "qa-project-report-archive.v1",
            "scope": "immutable_qa_report_draft",
            "id": archive_id,
            "project_id": project_id,
            "project_name": project["name"],
            "root_id": previous["root_id"] if previous else archive_id,
            "revision": previous["revision"] + 1 if previous else 1,
            "supersedes_id": payload.supersedes_id,
            "title": payload.title,
            "created_at_ms": self._time(),
            "template": template,
            "template_hash": fingerprint(template),
            "components": summaries,
            "markdown": _render(payload.title, project, template, summaries),
            "acceptance": "not_approved",
        }
        if document["revision"] > 1000:
            raise Conflict
        row = {key: document[key] for key in ("id", "project_id", "root_id", "revision", "supersedes_id", "title", "created_at_ms")}
        row.update(
            owner_id=owner, template_id=template["id"], template_version=template["version"], request_hash=request_hash, document=document, archive_hash=fingerprint({"owner_id": owner, "request_hash": request_hash, "document": document})
        )
        async with self._transaction() as session:
            # Serialize revision append at the project, then all run rows in ID order.
            # No network, decryption, hashing frozen datasets or rendering under locks.
            locked = (await session.execute(update(t.projects).where(t.projects.c.id == project_id, t.projects.c.owner_id == owner).values(id=t.projects.c.id).returning(t.projects))).mappings().first()
            if locked is None:
                raise NotFound
            if dict(locked) != project:
                raise Conflict
            existing = await self._archive_row(session, owner, project_id, archive_id)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return await asyncio.to_thread(self._decode, existing)
            if parent:
                if (
                    parent != await self._archive_row(session, owner, project_id, payload.supersedes_id)
                    or (await session.execute(select(t.report_archives.c.id).where(t.report_archives.c.project_id == project_id, t.report_archives.c.supersedes_id == payload.supersedes_id))).first()
                ):
                    raise Conflict
            locked_runs = []
            for snapshot in snapshots:  # DTO sorts sources by run ID.
                run = await self._journal(session, owner, project_id, snapshot["run"]["id"], lock=True)
                locked_runs.append(run)
                if snapshot != await self._summary_snapshot(session, owner, project_id, run["id"], run=run):
                    raise Conflict
            await session.execute(insert(t.report_archives).values(**row))
            for run in locked_runs:
                await self._journal_event(session, run, "report_archived", document["created_at_ms"])
        return {**document, "archive_hash": row["archive_hash"]}
