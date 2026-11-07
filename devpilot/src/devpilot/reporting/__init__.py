"""Version-pinned manual report previews; no storage, approval or target calls.

Keep this module independent from DeerFlow and rendering engines. Templates are
operator-controlled labels, never executable expressions or uploaded code.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
from dataclasses import asdict, dataclass
from typing import Any

RENDERER_VERSION = "manual-preview.v1"
SCHEMA_VERSION = "report-facts.v1"


class ReportValidationError(ValueError):
    """Invalid facts or unknown template; messages never contain submitted data."""


def _text(value: str, name: str, maximum: int = 200) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ReportValidationError(f"{name} must be nonblank text up to {maximum} characters")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ReportValidationError(f"{name} contains unsupported control characters")


def _count(value: int, name: str, minimum: int = 0) -> None:
    if type(value) is not int or not minimum <= value <= 10**9:
        raise ReportValidationError(f"{name} must be an integer between {minimum} and 1000000000")


def _measurement(value: float | None, name: str) -> None:
    if value is not None and (type(value) not in (int, float) or value < 0 or value > 10**15 or not math.isfinite(value)):
        raise ReportValidationError(f"{name} must be finite between 0 and 1000000000000000, or omitted")


@dataclass(frozen=True)
class EffectResults:
    total: int
    passed: int
    failed: int
    errors: int
    pending: int
    not_run: int

    def __post_init__(self):
        for name, value in asdict(self).items():
            _count(value, name, 1 if name == "total" else 0)
        if self.total != self.passed + self.failed + self.errors + self.pending + self.not_run:
            raise ReportValidationError("effect outcome counts must sum to total")


@dataclass(frozen=True)
class PerformanceResults:
    requests: int
    successful_requests: int
    concurrency: int
    metric_population: str = "successful_requests"
    latency_mean_ms: float | None = None
    latency_sample_count: int = 0
    content_streaming: bool = False
    ttft_mean_ms: float | None = None
    ttft_sample_count: int = 0
    throughput_tokens_per_s: float | None = None
    token_source: str = "unavailable"

    def __post_init__(self):
        _count(self.requests, "requests", 1)
        _count(self.successful_requests, "successful_requests")
        _count(self.concurrency, "concurrency", 1)
        _count(self.latency_sample_count, "latency_sample_count")
        _count(self.ttft_sample_count, "ttft_sample_count")
        if self.successful_requests > self.requests:
            raise ReportValidationError("successful_requests exceeds requests")
        if self.metric_population not in ("successful_requests", "all_attempts", "failed_attempts"):
            raise ReportValidationError("unknown metric_population")
        if type(self.content_streaming) is not bool:
            raise ReportValidationError("content_streaming must be a boolean")
        for name in ("latency_mean_ms", "ttft_mean_ms", "throughput_tokens_per_s"):
            _measurement(getattr(self, name), name)
        population = {
            "successful_requests": self.successful_requests,
            "all_attempts": self.requests,
            "failed_attempts": self.requests - self.successful_requests,
        }[self.metric_population]
        if self.latency_mean_ms is None:
            if self.latency_sample_count:
                raise ReportValidationError("latency samples require a measured mean")
        elif population == 0 or self.latency_sample_count != population:
            raise ReportValidationError("latency sample count must cover the selected population")
        if self.ttft_mean_ms is None:
            if self.ttft_sample_count:
                raise ReportValidationError("TTFT samples require a measured mean")
        elif not self.content_streaming or not 0 < self.ttft_sample_count <= self.successful_requests:
            raise ReportValidationError("TTFT requires content streaming and valid successful sample coverage")
        if self.token_source not in ("unavailable", "provider_usage", "tokenizer", "estimate"):
            raise ReportValidationError("unknown token_source")
        if self.throughput_tokens_per_s is not None and self.token_source == "unavailable":
            raise ReportValidationError("token throughput requires a token source")


@dataclass(frozen=True)
class ReportFacts:
    title: str
    project_name: str
    component_name: str
    component_version: str
    tester: str
    test_period: str
    environment: str
    scope: str
    methodology: str
    evidence_notes: str
    limitations: str
    evaluation_mode: str
    effect: EffectResults | None = None
    performance: PerformanceResults | None = None

    def __post_init__(self):
        for name in ("title", "project_name", "component_name", "component_version", "tester", "test_period"):
            _text(getattr(self, name), name)
        for name in ("environment", "scope", "methodology", "evidence_notes", "limitations"):
            _text(getattr(self, name), name, 2000)
        if self.evaluation_mode not in ("BASELINE", "ACCEPTANCE"):
            raise ReportValidationError("unknown evaluation_mode")
        if self.effect is None and self.performance is None:
            raise ReportValidationError("at least one result section is required")
        if self.effect is not None and not isinstance(self.effect, EffectResults):
            raise ReportValidationError("effect must be validated results")
        if self.performance is not None and not isinstance(self.performance, PerformanceResults):
            raise ReportValidationError("performance must be validated results")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportFacts:
        if not isinstance(data, dict):
            raise ReportValidationError("facts must be an object")
        fields = dict(data)
        try:
            for name, kind in (("effect", EffectResults), ("performance", PerformanceResults)):
                if fields.get(name) is not None:
                    if not isinstance(fields[name], dict):
                        raise ReportValidationError(f"{name} must be an object")
                    fields[name] = kind(**fields[name])
            return cls(**fields)
        except TypeError as exc:
            raise ReportValidationError("facts contain missing or unsupported fields") from exc


@dataclass(frozen=True)
class ReportTemplate:
    id: str
    version: str
    language: str
    name: str
    notice: str
    sections: tuple[str, ...]
    missing: str
    labels: tuple[tuple[str, str], ...]


_ZH_LABELS = (
    ("title", "报告标题"),
    ("project_name", "项目"),
    ("component_name", "组件"),
    ("component_version", "组件版本"),
    ("tester", "填报人（自述）"),
    ("test_period", "测试时间范围（自述）"),
    ("evaluation_mode", "评测模式"),
    ("environment", "环境"),
    ("scope", "范围"),
    ("methodology", "方法与统计口径"),
    ("evidence_notes", "证据说明（未核验）"),
    ("limitations", "限制与待确认项"),
    ("total", "总样本数"),
    ("passed", "通过"),
    ("failed", "不通过"),
    ("errors", "错误"),
    ("pending", "待审"),
    ("not_run", "未执行"),
    ("case_pass_rate", "二值通过率（通过/总数）"),
    ("requests", "请求总数"),
    ("successful_requests", "成功请求数"),
    ("concurrency", "并发"),
    ("success_rate", "调用成功率"),
    ("metric_population", "延迟统计范围"),
    ("latency_mean_ms", "平均响应时间（ms）"),
    ("latency_sample_count", "延迟样本数"),
    ("content_streaming", "声明已启用内容流式"),
    ("ttft_mean_ms", "平均 TTFT（ms）"),
    ("ttft_sample_count", "TTFT 样本数（成功请求子集）"),
    ("throughput_tokens_per_s", "整体吞吐（tokens/s）"),
    ("token_source", "Token 来源"),
)
_EN_LABELS = tuple((key, key.replace("_", " ")) for key, _ in _ZH_LABELS)
_TEMPLATES = (
    ReportTemplate(
        "component-evaluation-zh",
        "1.0.0",
        "zh",
        "AI 组件评测草稿",
        "DRAFT / 人工填报，数据未经核验、报告未经审批；不构成验收结论。请勿录入凭据或不必要的个人信息。",
        ("基本信息", "效果结果", "性能结果", "范围、证据与限制"),
        "未测量 / 不适用（见限制说明）",
        _ZH_LABELS,
    ),
    ReportTemplate(
        "component-evaluation-en",
        "1.0.0",
        "en",
        "AI component evaluation draft",
        "DRAFT / Manual, unverified input and unapproved report; not an acceptance decision. Do not include credentials or unnecessary personal data.",
        ("Overview", "Effect results", "Performance results", "Scope, evidence and limitations"),
        "Not measured / not applicable (see limitations)",
        _EN_LABELS,
    ),
)


def get_template(template_id: str, version: str) -> ReportTemplate:
    for template in _TEMPLATES:
        if (template.id, template.version) == (template_id, version):
            return template
    raise ReportValidationError("unknown template or template version")


def list_templates() -> list[dict[str, str]]:
    return [dict(id=t.id, version=t.version, language=t.language, name=t.name, schema_version=SCHEMA_VERSION) for t in _TEMPLATES]


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cell(value: Any) -> str:
    # User text is always a single escaped table cell, never Markdown structure.
    text = html.escape(str(value)).replace("\r", " ").replace("\n", " ")
    for char in ("\\", "|", "`", "*", "_", "[", "]", "#", "!"):
        text = text.replace(char, "\\" + char)
    return text


def build_preview(facts: ReportFacts, *, template: ReportTemplate, generated_by: str, generated_at: str) -> dict[str, Any]:
    snapshot = asdict(facts)
    derived = {
        "case_pass_rate": facts.effect.passed / facts.effect.total if facts.effect else None,
        "success_rate": facts.performance.successful_requests / facts.performance.requests if facts.performance else None,
    }
    labels = dict(template.labels)
    header = "| 字段 | 值 |" if template.language == "zh" else "| Field | Value |"
    lines = [f"# {template.name}", "", f"> {template.notice}", "", f"## {template.sections[0]}", "", header, "| --- | --- |"]

    def row(key: str, value: Any):
        if value is None:
            formatted = template.missing
        elif key in ("case_pass_rate", "success_rate"):
            formatted = f"{value:.2%}"
        else:
            formatted = str(value)
        lines.append(f"| {_cell(labels.get(key, key))} | {_cell(formatted)} |")

    row("title", facts.title)
    for key in ("project_name", "component_name", "component_version", "tester", "test_period", "evaluation_mode"):
        row(key, snapshot[key])
    for index, name, rate in ((1, "effect", "case_pass_rate"), (2, "performance", "success_rate")):
        lines.extend(["", f"## {template.sections[index]}", "", header, "| --- | --- |"])
        if snapshot[name] is None:
            row(name, None)
        else:
            for key, value in snapshot[name].items():
                row(key, value)
            row(rate, derived[rate])
    lines.extend(["", f"## {template.sections[3]}", "", header, "| --- | --- |"])
    for key in ("environment", "scope", "methodology", "evidence_notes", "limitations"):
        row(key, snapshot[key])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "template_id": template.id,
        "template_version": template.version,
        "renderer_version": RENDERER_VERSION,
        "facts_sha256": _digest(snapshot),
        "template_sha256": _digest(asdict(template)),
        "generated_by": generated_by,
        "generated_at": generated_at,
    }
    markdown = "\n".join(lines) + "\n\n## Manifest\n\n```json\n" + json.dumps(manifest, ensure_ascii=False, indent=2) + "\n```\n"
    return {
        "status": "DRAFT",
        "source": "manual_unverified",
        "template": asdict(template),
        "facts": snapshot,
        "derived": derived,
        "manifest": manifest,
        "markdown": markdown,
    }
