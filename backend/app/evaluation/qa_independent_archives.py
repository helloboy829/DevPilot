"""Explicit historical independent-assessment bindings for drafts and retests.

Separate namespaces/tables preserve owner-review archives. Only immutable public
assessment commitments and frozen plan/run metadata are read: never Q/A, gold,
owner votes, encrypted evidence, live tasks, model calls or approval authority.
"""

from __future__ import annotations

import copy
import hmac
import re

from pydantic import Field
from sqlalchemy import select

from app.evaluation import tables as t
from app.evaluation.criteria import assess_criteria
from app.evaluation.qa_assessments import AssessmentCreate, AssessmentRepository
from app.evaluation.qa_reports import ArchiveCreate, ArchiveSource, ReportArchiveRepository, _render, _safe
from app.evaluation.qa_retests import RetestCreate, RetestRepository, _pair_benchmark
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.evaluation.review_tasks import POLICY


class AssessmentSource(ArchiveSource):
    assessment_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    assessment_revision: int = Field(ge=1, le=1000, strict=True)
    assessment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class IndependentArchiveCreate(ArchiveCreate):
    sources: list[AssessmentSource] = Field(min_length=1, max_length=10)


class IndependentRetestCreate(RetestCreate):
    baseline: AssessmentSource
    retest: AssessmentSource


def independent_templates():
    """Pinned independent 1.0.0 layouts, not aliases of the owner catalog."""
    return [
        {
            "id": "independent-qa-project-en",
            "version": "1.0.0",
            "language": "en",
            "layout": {
                "heading": "Independent QA assessment report — DRAFT / NOT APPROVED",
                "project": "Project",
                "notice": (
                    "Selected historical independent double-blind assessment revisions, not current review state or formal approval. "
                    "Independent PASS / ALL frozen samples; no owner votes or pooled cross-component rate. "
                    "Later reopens or revisions do not rewrite this draft."
                ),
                "columns": "Component | Frozen plan | Independent PASS / All samples | Independent pass rate",
                "sources": "Frozen independent assessment references",
                "footer": "Each component explicitly binds an immutable independent assessment ID, revision and integrity hash. Further revisions create a new archive. Hashes are not external signatures.",
                "criteria_heading": "Frozen effectiveness criteria (not formal approval)",
                "criteria_columns": "Component | Criteria version | Minimum independent pass rate | Threshold status (not approved)",
                "criteria_notice": "met: effectiveness threshold met; not_met: threshold not met; incomplete: incomplete evidence; not_configured: no pre-run frozen criteria. None means performance acceptance or project approval.",
            },
        },
        {
            "id": "independent-qa-project-zh",
            "version": "1.0.0",
            "language": "zh",
            "layout": {
                "heading": "独立 QA 评估报告 — 草稿 / 未批准（DRAFT）",
                "project": "项目",
                "notice": "独立双盲复核的指定历史评估修订，不是当前复核状态或正式批准。独立通过率＝独立 PASS / 全部冻结样本；不混入 owner 自复核、不跨组件平均。后续重开或评估修订不改写本档案。",
                "columns": "组件 | 冻结计划 | 独立通过数 / 全部样本 | 独立通过率",
                "sources": "冻结独立评估引用",
                "footer": "每个组件显式绑定不可变独立评估 ID、修订和完整性哈希；后续修订另建档案。哈希不是外部数字签章。",
                "criteria_heading": "冻结效果标准（不是正式批准）",
                "criteria_columns": "组件 | 标准版本 | 最低独立通过率 | 标准判定（未批准）",
                "criteria_notice": "met＝效果阈值达标；not_met＝未达标；incomplete＝证据不完整；not_configured＝执行前未冻结标准。均不代表性能合格或项目批准。",
            },
        },
    ]


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _archived_source(summary):
    return AssessmentSource(run_id=summary["run_id"], summary_hash=summary["summary_hash"], **summary["assessment_ref"])


class IndependentSources:
    def _source_protection(self):
        # Historical commitments do not require decrypting today's evidence.
        return None

    async def _source_snapshot(self, session, owner, project_id, source, *, run=None):
        run = run if run is not None else await self._journal(session, owner, project_id, source.run_id)
        plan = (await session.execute(select(t.plans).where(t.plans.c.id == run["plan_id"], t.plans.c.project_id == project_id))).mappings().first()
        if plan is None:
            raise Conflict
        component = (await session.execute(select(t.project_components.c.id, t.project_components.c.project_id).where(t.project_components.c.id == plan["component_id"], t.project_components.c.project_id == project_id))).mappings().first()
        row = (
            (
                await session.execute(
                    select(t.run_assessments).where(t.run_assessments.c.id == source.assessment_id, t.run_assessments.c.owner_id == owner, t.run_assessments.c.project_id == project_id, t.run_assessments.c.run_id == source.run_id)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise NotFound
        if component is None:
            raise Conflict
        dispatches = [dict(item) for item in (await session.execute(select(t.dispatches.c.ordinal, t.dispatches.c.sample_id).where(t.dispatches.c.run_id == source.run_id).order_by(t.dispatches.c.ordinal).limit(501))).mappings()]
        return {"run": run, "plan": dict(plan), "component": dict(component), "assessment": dict(row), "dispatches": dispatches, "viewed": source.model_dump()}

    def _verify_frozen_source(self, owner, snapshot):
        try:
            return self._verified_frozen_source(owner, snapshot)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise Conflict from None

    def _verified_frozen_source(self, owner, snapshot):
        run, raw, viewed = snapshot["run"], snapshot["assessment"], snapshot["viewed"]
        if raw["owner_id"] != owner or any(raw[key] != run[key] for key in ("project_id",)) or raw["run_id"] != run["id"]:
            raise Conflict
        document = AssessmentRepository._decode_assessment(raw)
        summary = document["assessment"]
        request = AssessmentCreate(summary_hash=viewed["summary_hash"], expected_previous_revision=viewed["assessment_revision"] - 1, confirmed=True)
        if fingerprint(request.model_dump()) != raw["request_hash"]:
            raise Conflict
        if not isinstance(summary["component_name"], str) or not 1 <= len(summary["component_name"]) <= 255:
            raise Conflict
        plan = self._public_plan(snapshot["plan"])
        definition = plan["definition"]
        if (document["id"], document["revision"], document["assessment_hash"], summary["summary_hash"]) != (viewed["assessment_id"], viewed["assessment_revision"], viewed["assessment_hash"], viewed["summary_hash"]):
            raise Conflict
        if run["id"] != viewed["run_id"] or run["status"] != "recording_finished" or run["plan_hash"] != plan["definition_hash"]:
            raise Conflict
        if summary["schema"] != "qa-independent-assessment-preview.v1" or summary["scope"] != "verified_independent_assessment_preview" or summary["acceptance"] != "not_approved":
            raise Conflict
        expected = {"id": POLICY, "population": "all_frozen_effectiveness_samples", "timing": "post_collection_assessment"}
        if summary["policy"] != expected or summary["readiness"] != "review_complete" or summary["blockers"] != [] or summary["run_status"] != "recording_finished":
            raise Conflict
        if any(
            summary[key] != value
            for key, value in {"run_id": run["id"], "project_id": run["project_id"], "plan_id": plan["id"], "plan_hash": plan["definition_hash"], "plan_label": plan["version_label"], "component_id": snapshot["component"]["id"]}.items()
        ):
            raise Conflict
        total = run["request_count"]
        if definition["limits"]["mode"] != "effectiveness" or not _integer(total, 1, 500) or total != definition["preflight"]["sample_count"] or total != definition["limits"]["request_count"] or total != len(summary["cases"]):
            raise Conflict
        dispatches = snapshot["dispatches"]
        if len(dispatches) != total or [d["ordinal"] for d in dispatches] != list(range(1, total + 1)):
            raise Conflict
        sample_ids = [d["sample_id"] for d in dispatches]
        if any(not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) is None for value in sample_ids) or sample_ids != sorted(set(sample_ids)):
            raise Conflict
        counts = {"pass": 0, "fail": 0, "uncertain": 0, "unreviewed": 0}
        seen = set()
        for ordinal, case in enumerate(summary["cases"], 1):
            if (
                set(case) != {"ordinal", "case_hash", "outcome", "tasks"}
                or type(case["ordinal"]) is not int
                or case["ordinal"] != ordinal
                or not _hash(case["case_hash"])
                or case["outcome"] not in {"pass", "fail"}
                or not isinstance(case["tasks"], list)
                or not 1 <= len(case["tasks"]) <= 10000
            ):
                raise Conflict
            counts[case["outcome"]] += 1
            for task in case["tasks"]:
                if set(task) != {"task_id", "subject_hash", "round", "task_revision", "status", "resolution_revision", "resolution_hash"}:
                    raise Conflict
                self._identifier(task["task_id"])
                if (
                    task["task_id"] in seen
                    or task["status"] != "resolved"
                    or not _integer(task["round"], 1, 10)
                    or not _integer(task["task_revision"], 1, 10000)
                    or not _integer(task["resolution_revision"], 1, 2)
                    or not all(_hash(task[k]) for k in ("subject_hash", "resolution_hash"))
                ):
                    raise Conflict
                seen.add(task["task_id"])
                if len(seen) > 10000:
                    raise Conflict
        if set(summary["counts"]) != set(counts) or any(type(v) is not int for v in summary["counts"].values()) or summary["counts"] != counts:
            raise Conflict
        rate = {"numerator": counts["pass"], "denominator": total, "value": counts["pass"] / total}
        if (
            summary["human_pass_rate"] != rate
            or any(type(summary["human_pass_rate"][k]) is not int for k in ("numerator", "denominator"))
            or type(summary["human_pass_rate"]["value"]) is not float
            or summary["technical_counts"] != {"collected": total, "other": 0}
            or any(type(v) is not int for v in summary["technical_counts"].values())
        ):
            raise Conflict
        if "acceptance_criteria" in definition:
            if fingerprint(summary["criteria_evaluation"]) != fingerprint(assess_criteria(definition["acceptance_criteria"], counts["pass"], total, [])):
                raise Conflict
        elif "criteria_evaluation" in summary:
            raise Conflict
        keys = {
            "schema",
            "scope",
            "policy",
            "run_id",
            "run_status",
            "project_id",
            "component_id",
            "component_name",
            "plan_id",
            "plan_label",
            "plan_hash",
            "counts",
            "technical_counts",
            "human_pass_rate",
            "readiness",
            "blockers",
            "acceptance",
            "cases",
            "summary_hash",
        }
        if "acceptance_criteria" in definition:
            keys.add("criteria_evaluation")
        if set(summary) != keys or not hmac.compare_digest(fingerprint({k: v for k, v in summary.items() if k != "summary_hash"}), summary["summary_hash"]):
            raise Conflict
        return {**copy.deepcopy(summary), "assessment_ref": {key: viewed[key] for key in ("assessment_id", "assessment_revision", "assessment_hash")}}


class IndependentReportRepository(IndependentSources, ReportArchiveRepository):
    _archive_table = t.independent_report_archives
    _archive_schema = "qa-independent-project-report-archive.v1"
    _archive_scope = "immutable_independent_qa_report_draft"
    _create_model = IndependentArchiveCreate
    _audit_kind = "independent_report_archived"

    @classmethod
    def _decode(cls, row):
        document = super()._decode(row)
        try:
            sources = [_archived_source(item) for item in document["components"]]
            request = IndependentArchiveCreate(title=document["title"], template_id=document["template"]["id"], template_version=document["template"]["version"], sources=sources, supersedes_id=document["supersedes_id"], confirmed=True)
            if fingerprint(request.model_dump()) != row["request_hash"] or fingerprint(document["template"]) != document["template_hash"]:
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestProtectionError("Independent report integrity check failed") from None
        return document

    @staticmethod
    def templates():
        return independent_templates()

    def _verify_sources(self, owner, snapshots, _protection):
        summaries = [self._verify_frozen_source(owner, snapshot) for snapshot in snapshots]
        if len({item["component_id"] for item in summaries}) != len(summaries):
            raise Conflict
        return sorted(summaries, key=lambda item: item["component_id"])

    @staticmethod
    def _render(title, project, template, summaries):
        markdown = _render(title, project, template, summaries)
        lines = [markdown, "", "## Independent assessment revisions / 独立评估修订", ""]
        for summary in summaries:
            ref = summary["assessment_ref"]
            lines.extend(["- " + _safe(summary["component_name"]), "  - Assessment: " + ref["assessment_id"], "  - Revision: " + str(ref["assessment_revision"]), "  - Receipt: " + ref["assessment_hash"], "  - Policy: " + POLICY])
        return "\n".join(lines)


class IndependentRetestRepository(IndependentSources, RetestRepository):
    _retest_table = t.independent_retest_archives
    _archive_schema = "qa-independent-retest-archive.v1"
    _archive_scope = "same_benchmark_independent_comparison"
    _create_model = IndependentRetestCreate
    _audit_kind = "independent_retest_archived"
    _pair_columns = ("baseline_assessment_id", "retest_assessment_id")

    @classmethod
    def _decode(cls, row):
        document = super()._decode(row)
        try:
            sources = {side: _archived_source(document[side]) for side in ("baseline", "retest")}
            request = IndependentRetestCreate(**sources, confirmed=True)
            if fingerprint(request.model_dump()) != row["request_hash"] or any(sources[side].assessment_id != row[side + "_assessment_id"] for side in sources):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestProtectionError("Independent retest integrity check failed") from None
        return document

    def _pair_values(self, payload):
        return payload.baseline.assessment_id, payload.retest.assessment_id

    def _extra_row(self, payload):
        return dict(zip(self._pair_columns, self._pair_values(payload), strict=True))

    def _verify_pair(self, owner, snapshots, _protection, _payload):
        summaries = [self._verify_frozen_source(owner, snapshot) for snapshot in snapshots]
        benchmark = _pair_benchmark(snapshots)
        if summaries[0]["policy"] != summaries[1]["policy"]:
            raise Conflict
        benchmark["independent_policy"] = summaries[0]["policy"]
        old, new = [snapshot["plan"]["definition"] for snapshot in snapshots]
        if snapshots[0]["dispatches"] != snapshots[1]["dispatches"]:
            raise Conflict
        cases, transitions = [], {key: 0 for key in ("fail_to_pass", "pass_to_fail", "pass_to_pass", "fail_to_fail")}
        for dispatch, left, right in zip(snapshots[0]["dispatches"], summaries[0]["cases"], summaries[1]["cases"], strict=True):
            transition = left["outcome"] + "_to_" + right["outcome"]
            transitions[transition] += 1
            case = {"ordinal": left["ordinal"], "sample_id": dispatch["sample_id"], "transition": transition}
            for side, decision in (("baseline", left), ("retest", right)):
                case.update({side + "_decision": decision["outcome"], side + "_case_hash": decision["case_hash"], side + "_tasks": decision["tasks"]})
            cases.append(case)
        denominator = summaries[0]["human_pass_rate"]["denominator"]
        if summaries[1]["human_pass_rate"]["denominator"] != denominator or len(cases) != denominator:
            raise Conflict
        numerator = summaries[1]["human_pass_rate"]["numerator"] - summaries[0]["human_pass_rate"]["numerator"]
        return {
            "baseline": summaries[0],
            "retest": summaries[1],
            "benchmark": benchmark,
            "benchmark_hash": fingerprint(benchmark),
            "request_definition_changed": any(old[key] != new[key] for key in ("request_version_id", "request_protected_hash", "request_template_fingerprint")),
            "transitions": transitions,
            "cases": cases,
            "pass_rate_delta": {"numerator": numerator, "denominator": denominator, "value": numerator / denominator},
        }
