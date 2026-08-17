"""效果测试（effect test）：执行与评估分离。

- ``effect_run``：逐样本调接口 → 收集 raw（原始返回）。只落盘，不判定。
- ``effect_eval``：按 ``validation_type`` 分发判定 → 对照 ``acceptance_criteria.effect``
  硬阈值 → PASS / FAIL。

铁律（源自 skill 的 pitfalls）：

- **执行 / 评估分离**：``effect_run`` 只产出原始返回，``effect_eval`` 只读 raw，
  支持显式传 raw 文件路径反复重评。
- **MANUAL_REVIEW 不计入自动通过率**：手动评审样本既不抬高也不拉低自动判定。
- ``reference_text`` 走 LLM-as-Judge：复用 ``devpilot.evaluation.judge`` 的
  ``strip_think_blocks`` + 稳健 JSON 解析，但换新 schema（accuracy/completeness/structure），
  不再用 7 字段。

LLM 调用在 ``judge_reference_text`` 里惰性 import deerflow，保证纯逻辑部分可独立单测。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from devpilot.evaluation.judge import clamp_score, strip_think_blocks
from devpilot.toolkit.transports import TransportConfig, TransportResult, call_transport

#: 效果判定 schema 的 camelCase 字段（对外契约）。
_EFFECT_FIELDS: tuple[str, ...] = ("accuracy", "completeness", "structure", "overall", "report")

#: 自动判定（计入自动通过率）的验证类型；manual_review 之外。
AUTO_VALIDATION_TYPES: frozenset[str] = frozenset({"reference_text"})


@dataclass
class EffectJudgeResult:
    """效果评测（LLM-as-Judge）的归一化结果。"""

    accuracy: float = 0.0  # 准确性 0-100
    completeness: float = 0.0  # 完整性 0-100
    structure: float = 0.0  # 结构/格式 0-100
    overall: float = 0.0  # 综合 0-100
    report: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.accuracy = clamp_score(self.accuracy)
        self.completeness = clamp_score(self.completeness)
        self.structure = clamp_score(self.structure)
        self.overall = clamp_score(self.overall)
        if not isinstance(self.report, str):
            self.report = str(self.report or "")

    def fill_overall(self) -> "EffectJudgeResult":
        """overall 未给出时用均分回填。"""
        if self.overall <= 0:
            self.overall = round((self.accuracy + self.completeness + self.structure) / 3, 2)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy": round(self.accuracy, 2),
            "completeness": round(self.completeness, 2),
            "structure": round(self.structure, 2),
            "overall": round(self.overall, 2),
            "report": self.report,
        }


@dataclass
class EffectThresholds:
    """效果验收硬阈值。0 表示不设该维度门槛。"""

    accuracy_min: float = 0.0
    completeness_min: float = 0.0
    structure_min: float = 0.0
    overall_min: float = 0.0

    @classmethod
    def from_criteria(cls, criteria: Mapping[str, Any] | None) -> "EffectThresholds":
        effect = (criteria or {}).get("effect") or {}
        return cls(
            accuracy_min=float(effect.get("accuracy_min") or 0.0),
            completeness_min=float(effect.get("completeness_min") or 0.0),
            structure_min=float(effect.get("structure_min") or 0.0),
            overall_min=float(effect.get("overall_min") or 0.0),
        )


@dataclass
class EffectSampleResult:
    """单个样本的效果判定结果。"""

    sample_index: int
    validation_type: str
    status: str  # passed | failed | manual_review | error
    judge: EffectJudgeResult | None = None
    reference_text: str | None = None
    output_text: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_index": self.sample_index,
            "validation_type": self.validation_type,
            "status": self.status,
            "judge": self.judge.to_dict() if self.judge else None,
            "reference_text": self.reference_text,
            "output_text": self.output_text,
            "error": self.error,
        }


@dataclass
class EffectReport:
    """效果测试汇总报告。"""

    total: int = 0
    passed: int = 0
    failed: int = 0
    manual_review: int = 0
    error: int = 0
    auto_total: int = 0  # total - manual_review
    auto_pass_rate: float = 0.0
    overall: str = "REVIEW"  # PASS | FAIL | REVIEW
    samples: list[EffectSampleResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "manual_review": self.manual_review,
            "error": self.error,
            "auto_total": self.auto_total,
            "auto_pass_rate": round(self.auto_pass_rate, 4),
            "overall": self.overall,
            "summary": self.summary,
            "samples": [s.to_dict() for s in self.samples],
        }


def _strip_code_fences(text: str) -> str:
    """剥离 ```json ... ``` / ``` ... ``` 围栏。"""
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    if text.lstrip().startswith("```"):
        return re.sub(r"^```[a-zA-Z]*\s*\n?", "", text).strip()
    return text.strip()


def parse_effect_judge_output(text: str) -> EffectJudgeResult:
    """从 LLM 原始输出解析效果 schema（accuracy/completeness/structure/overall/report）。

    容错策略同 judge.parse_judge_output：剥离 think + 代码围栏 → 取 JSON → 失败返回
    accuracy=0 且 report 记录解析失败。
    """
    cleaned = strip_think_blocks(text, truncate_unclosed=True)
    cleaned = _strip_code_fences(cleaned)

    candidates: list[str] = []
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])
    candidates.extend(re.findall(r"\{[^{}]*\}", cleaned))

    last_error: Exception | None = None
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return _effect_result_from_mapping(data)
        except (json.JSONDecodeError, TypeError) as exc:  # noqa: PERF203
            last_error = exc

    return EffectJudgeResult(
        overall=0.0,
        report=f"[解析失败] 无法从模型输出提取效果评测 JSON：{last_error or '未找到 JSON 对象'}",
        details={"raw": text[:500]},
    )


def _effect_result_from_mapping(data: Mapping[str, Any]) -> EffectJudgeResult:
    result = EffectJudgeResult(
        accuracy=data.get("accuracy", data.get("准确性", 0.0)),
        completeness=data.get("completeness", data.get("完整性", 0.0)),
        structure=data.get("structure", data.get("结构", 0.0)),
        overall=data.get("overall", data.get("综合", 0.0)),
        report=data.get("report", data.get("报告", "")),
    )
    return result.fill_overall()


def build_effect_judge_prompt(output_text: str, reference_text: str) -> str:
    """构造效果评测（reference_text）的 LLM prompt。"""
    return f"""你是一名严格的 AI 组件效果评测专家（LLM-as-Judge）。请对比「组件实际输出」与「参考答案」，给出客观评分。

【参考答案】
{reference_text or "（未提供参考答案）"}

【组件实际输出】
{output_text or "（组件无输出）"}

请只输出一个 JSON 对象（不要输出其它文字），包含以下 5 个字段：

- accuracy (0-100)：准确性——输出内容与参考答案的事实是否一致、有无错误或幻觉。
- completeness (0-100)：完整性——参考答案的关键信息点是否都被覆盖，有无遗漏。
- structure (0-100)：结构/格式——输出是否结构清晰、格式规范、符合该组件应有的形态。
- overall (0-100)：综合评分。
- report (字符串)：一段不超过 150 字的中文评测摘要，点明主要优点与最关键的问题。

评分要求：
1. 每项分数必须有输出/参考答案的证据支撑，禁止凭空打分。
2. 输出为空或完全无关时，accuracy/completeness/structure/overall 均应接近 0。

仅输出 JSON：
{{"accuracy": 0, "completeness": 0, "structure": 0, "overall": 0, "report": "..."}}"""


async def judge_reference_text(
    output_text: str,
    reference_text: str,
    *,
    model_name: str | None = None,
) -> EffectJudgeResult:
    """用 DeerFlow 配置的模型执行一次效果评测（reference_text），失败 fail-open。"""
    from devpilot.toolkit.effect import build_effect_judge_prompt, parse_effect_judge_output

    prompt = build_effect_judge_prompt(output_text, reference_text)
    try:
        from deerflow.models import create_chat_model

        model = create_chat_model(name=model_name, thinking_enabled=False, attach_tracing=False)
        response = await model.ainvoke(
            [
                ("system", "你是一名 AI 组件效果评测专家。只输出一个合法 JSON 对象，不输出解释、Markdown 或思维链。"),
                ("human", prompt),
            ]
        )
        content = getattr(response, "content", None)
        if isinstance(content, list):
            parts = []
            for piece in content:
                if isinstance(piece, str):
                    parts.append(piece)
                elif isinstance(piece, Mapping) and piece.get("type") == "text":
                    parts.append(str(piece.get("text", "")))
            content = "".join(parts)
        return parse_effect_judge_output(str(content or ""))
    except Exception as exc:  # noqa: BLE001 - 评测 fail-open，记录并降级。
        return EffectJudgeResult(
            overall=0.0,
            report=f"[评测失败] 模型调用异常：{exc}",
        )


# ── 执行 / 评估 ──────────────────────────────────────────────────────────


async def effect_run(
    config: TransportConfig,
    samples: Sequence[Mapping[str, Any]],
    *,
    client: Any = None,
    stream: bool | None = None,
) -> list[TransportResult]:
    """逐个样本调接口，返回归一化的原始返回（不做判定）。

    每个样本是 transport 对应的请求载荷（见 transports 的 body 构造约定）。
    """
    results: list[TransportResult] = []
    for sample in samples:
        results.append(await call_transport(config, sample, client=client, stream=stream))
    return results


def _judge_meets_thresholds(judge: EffectJudgeResult, thresholds: EffectThresholds) -> bool:
    return (
        judge.accuracy >= thresholds.accuracy_min
        and judge.completeness >= thresholds.completeness_min
        and judge.structure >= thresholds.structure_min
        and judge.overall >= thresholds.overall_min
    )


async def effect_eval(
    results: Sequence[TransportResult],
    *,
    validation_type: str,
    samples: Sequence[Mapping[str, Any]] | None = None,
    criteria: Mapping[str, Any] | None = None,
    model_name: str | None = None,
) -> EffectReport:
    """按验证类型对原始返回做效果判定，汇总成 PASS/FAIL 报告。

    ``samples`` 提供每个样本的 ``reference_text``（reference_text 验证类型需要）。
    ``criteria`` 即组件注册表的 ``acceptance_criteria``（含 ``effect`` 硬阈值）。
    """
    thresholds = EffectThresholds.from_criteria(criteria)
    sample_results: list[EffectSampleResult] = []
    samples = samples or [{} for _ in results]

    for idx, result in enumerate(results):
        meta = samples[idx] if idx < len(samples) else {}
        if validation_type == "manual_review":
            sample_results.append(
                EffectSampleResult(
                    sample_index=idx,
                    validation_type=validation_type,
                    status="manual_review",
                    reference_text=None,
                    output_text=result.text,
                )
            )
            continue

        if validation_type == "reference_text":
            reference_text = str(meta.get("reference_text") or "")
            if not result.success:
                sample_results.append(
                    EffectSampleResult(
                        sample_index=idx,
                        validation_type=validation_type,
                        status="error",
                        reference_text=reference_text,
                        output_text=result.text,
                        error=result.error or "调用失败",
                    )
                )
                continue
            judge = await judge_reference_text(result.text, reference_text, model_name=model_name)
            passed = _judge_meets_thresholds(judge, thresholds)
            # 评测解析失败（overall=0 且 report 含解析/评测失败）视为 failed，不吞掉。
            if judge.overall <= 0 and "失败" in judge.report:
                passed = False
            sample_results.append(
                EffectSampleResult(
                    sample_index=idx,
                    validation_type=validation_type,
                    status="passed" if passed else "failed",
                    judge=judge,
                    reference_text=reference_text,
                    output_text=result.text,
                )
            )
            continue

        # 尚未支持的验证类型（M7 补 reference_values / field_completeness / structure）。
        sample_results.append(
            EffectSampleResult(
                sample_index=idx,
                validation_type=validation_type,
                status="error",
                error=f"不支持的验证类型: {validation_type}",
                output_text=result.text,
            )
        )

    return _build_effect_report(sample_results)


def _build_effect_report(samples: Sequence[EffectSampleResult]) -> EffectReport:
    report = EffectReport(total=len(samples), samples=list(samples))
    auto_judged: list[EffectSampleResult] = []
    for s in samples:
        if s.status == "passed":
            report.passed += 1
            auto_judged.append(s)
        elif s.status == "failed":
            report.failed += 1
            auto_judged.append(s)
        elif s.status == "manual_review":
            report.manual_review += 1
        else:  # error
            report.error += 1
            auto_judged.append(s)

    report.auto_total = len(auto_judged)
    report.auto_pass_rate = (report.passed / report.auto_total) if report.auto_total else 0.0

    if report.auto_total == 0:
        report.overall = "REVIEW"
    elif report.failed == 0 and report.error == 0:
        report.overall = "PASS"
    else:
        report.overall = "FAIL"

    judged = [s for s in auto_judged if s.judge is not None]
    if judged:
        n = len(judged)
        report.summary = {
            "avg_accuracy": round(sum(j.judge.accuracy for j in judged) / n, 2),
            "avg_completeness": round(sum(j.judge.completeness for j in judged) / n, 2),
            "avg_structure": round(sum(j.judge.structure for j in judged) / n, 2),
            "avg_overall": round(sum(j.judge.overall for j in judged) / n, 2),
        }
    return report


__all__ = [
    "AUTO_VALIDATION_TYPES",
    "EffectJudgeResult",
    "EffectThresholds",
    "EffectSampleResult",
    "EffectReport",
    "build_effect_judge_prompt",
    "parse_effect_judge_output",
    "judge_reference_text",
    "effect_run",
    "effect_eval",
    "_build_effect_report",
]
