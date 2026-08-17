"""LLM-as-Judge 核心：7 字段评分。

本模块**纯逻辑、零外部依赖**（不 import deerflow、不做网络请求），
便于离线单测，也便于真实评测复用一个稳定的 schema + 解析逻辑。

7 字段（源自 docs/DevPilot_系统架构设计.md）：

    taskScore          任务完成度         0-100
    codeScore          代码质量           0-100
    testScore          测试评分           0-100
    hallucinationRate  幻觉率             0-1
    confidence         置信度             0-100
    overall            综合评分           0-100
    report             评测报告摘要       字符串
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: 7 字段的 camelCase 名称（对外契约，评测报告 JSON 的键）。
SEVEN_FIELDS: tuple[str, ...] = (
    "taskScore",
    "codeScore",
    "testScore",
    "hallucinationRate",
    "confidence",
    "overall",
    "report",
)

#: camelCase -> snake_case 字段映射，用于解析模型返回的任意拼写。
_CAMEL_TO_SNAKE: dict[str, str] = {
    "taskScore": "task_score",
    "codeScore": "code_score",
    "testScore": "test_score",
    "hallucinationRate": "hallucination_rate",
    "confidence": "confidence",
    "overall": "overall",
    "report": "report",
}

#: snake_case 别名的逆映射（解析时兼容 snake_case 输入）。
_SNAKE_ALIASES: dict[str, str] = {
    "task_score": "task_score",
    "code_score": "code_score",
    "test_score": "test_score",
    "hallucination_rate": "hallucination_rate",
    "confidence": "confidence",
    "overall": "overall",
    "report": "report",
}

#: 综合评分权重（task/code/test/confidence），幻觉率作为乘法惩罚因子。
_OVERALL_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("task_score", 0.35),
    ("code_score", 0.30),
    ("test_score", 0.20),
    ("confidence", 0.15),
)


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp ``value`` into ``[lo, hi]``，对非数值返回 ``lo``（保守失败）。"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return float(lo)
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return float(lo)


def clamp_score(value: Any) -> float:
    """0-100 评分归一化。"""
    return _clamp(value, 0.0, 100.0)


def clamp_rate(value: Any) -> float:
    """0-1 比率（幻觉率）归一化。"""
    return _clamp(value, 0.0, 1.0)


def compute_overall(
    task_score: float,
    code_score: float,
    test_score: float,
    confidence: float,
    hallucination_rate: float,
) -> float:
    """确定性综合评分：加权平均 × (1 - 幻觉率)，再 clamp 到 0-100。

    仅作为「模型漏填 overall」时的兜底，或 metrics 聚合时的交叉校验；
    模型显式给出的 ``overall`` 仍优先。
    """
    weighted = (
        task_score * 0.35
        + code_score * 0.30
        + test_score * 0.20
        + confidence * 0.15
    )
    penalized = weighted * (1.0 - clamp_rate(hallucination_rate))
    return round(clamp_score(penalized))


@dataclass
class EvaluationResult:
    """7 字段评测结果。

    字段命名用 snake_case（内部），对外序列化用 camelCase（契约）。
    ``details`` 承载可选的评分依据（分维度理由/发现清单），不属于契约字段，
    但可供报告展示与幻觉率交叉审计使用。
    """

    task_score: float = 0.0
    code_score: float = 0.0
    test_score: float = 0.0
    hallucination_rate: float = 0.0
    confidence: float = 0.0
    overall: float = 0.0
    report: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """入库即归一化：评分 clamp 到 0-100，幻觉率 clamp 到 0-1。"""
        self.task_score = clamp_score(self.task_score)
        self.code_score = clamp_score(self.code_score)
        self.test_score = clamp_score(self.test_score)
        self.hallucination_rate = clamp_rate(self.hallucination_rate)
        self.confidence = clamp_score(self.confidence)
        self.overall = clamp_score(self.overall)
        if not isinstance(self.report, str):
            self.report = str(self.report or "")

    def fill_overall(self) -> "EvaluationResult":
        """当 overall 未给出（<=0 视为漏填）时，用确定性公式回填。"""
        if self.overall <= 0:
            self.overall = compute_overall(
                self.task_score,
                self.code_score,
                self.test_score,
                self.confidence,
                self.hallucination_rate,
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        """序列化为契约 JSON（camelCase）。"""
        return {
            "taskScore": round(self.task_score, 2),
            "codeScore": round(self.code_score, 2),
            "testScore": round(self.test_score, 2),
            "hallucinationRate": round(self.hallucination_rate, 4),
            "confidence": round(self.confidence, 2),
            "overall": round(self.overall, 2),
            "report": self.report,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EvaluationResult":
        """从任意字段名（camelCase 或 snake_case）的映射构造。"""
        resolved: dict[str, Any] = {}
        for key, value in data.items():
            if not isinstance(key, str):
                continue
            snake = _CAMEL_TO_SNAKE.get(key) or _SNAKE_ALIASES.get(key)
            if snake:
                resolved[snake] = value
        # 把 details 之外的额外键收进 details，供审计。
        extra = {k: v for k, v in data.items() if isinstance(k, str) and k not in _CAMEL_TO_SNAKE and k not in _SNAKE_ALIASES}
        result = cls(
            task_score=resolved.get("task_score", 0.0),
            code_score=resolved.get("code_score", 0.0),
            test_score=resolved.get("test_score", 0.0),
            hallucination_rate=resolved.get("hallucination_rate", 0.0),
            confidence=resolved.get("confidence", 0.0),
            overall=resolved.get("overall", 0.0),
            report=resolved.get("report", ""),
            details=extra,
        )
        return result.fill_overall()


def strip_think_blocks(text: str, truncate_unclosed: bool = False) -> str:
    """剥离 ``<think>...</think>`` 推理块（含未闭合/截断的）。

    与上游 ``deerflow.utils.llm_text.strip_think_blocks`` 语义一致，
    但这里零依赖复刻一份，保证纯逻辑模块可独立运行。
    """
    if not text:
        return ""
    # 已闭合的 think 块
    text = re.sub(r"<think[^>]*>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    if truncate_unclosed:
        # 只保留第一个未闭合 <think> 之前的内容
        idx = re.search(r"<think[^>]*>", text, flags=re.IGNORECASE)
        if idx:
            text = text[: idx.start()]
    return text


def _strip_code_fences(text: str) -> str:
    """剥离 ```json ... ``` / ``` ... ``` 围栏。"""
    # 优先匹配 ```json 或 ```JSON
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    # 只有开围栏、无闭围栏的情况
    if text.lstrip().startswith("```"):
        return re.sub(r"^```[a-zA-Z]*\s*\n?", "", text).strip()
    return text.strip()


def parse_judge_output(text: str) -> EvaluationResult:
    """从模型原始输出解析 7 字段。

    容错策略：
      1. 剥离 think 推理块与代码围栏；
      2. 定位第一个 ``{`` 到最后一个 ``}`` 之间的 JSON；
      3. 解析失败则尝试在整个文本里找 JSON 对象；
      4. 仍失败则返回一个 overall=0 的空结果（report 记录解析失败原因）。
    """
    cleaned = strip_think_blocks(text, truncate_unclosed=True)
    cleaned = _strip_code_fences(cleaned)

    candidates = []
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])
    # 兜底：扫描所有 {...} 片段（模型可能夹带说明文字）。
    candidates.extend(re.findall(r"\{[^{}]*\}", cleaned))

    last_error: Exception | None = None
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return EvaluationResult.from_mapping(data)
        except (json.JSONDecodeError, TypeError) as exc:  # noqa: PERF203
            last_error = exc

    # 彻底失败：返回空结果，report 记录原因，便于上游观测。
    return EvaluationResult(
        overall=0.0,
        report=f"[解析失败] 无法从模型输出提取 7 字段 JSON：{last_error or '未找到 JSON 对象'}",
        details={"raw": text[:500]},
    )


def build_prompt(
    requirement: str,
    artifacts: Mapping[str, str],
    test_summary: str = "",
    transcript_excerpt: str = "",
) -> str:
    """构造 LLM-as-Judge 的评测 prompt。

    ``artifacts``：文件名 -> 文件内容（或摘要）的映射，作为评分证据。
    ``test_summary``：测试运行结果（通过数/失败数/输出摘要）。
    ``transcript_excerpt``：研发过程的对话摘要（用于幻觉率与置信度判断）。
    """
    artifact_block = "\n\n".join(
        f"### 文件：{name}\n```\n{content[:4000]}\n```" for name, content in artifacts.items()
    ) or "（无产物文件）"

    return f"""你是一名严格的研发评审专家（LLM-as-Judge）。请基于以下材料，对一次研发任务给出客观评分。

【任务需求】
{requirement or "（未提供需求）"}

【研发过程摘要】
{transcript_excerpt or "（未提供过程）"}

【测试运行结果】
{test_summary or "（未提供测试）"}

【产物文件】
{artifact_block}

请只输出一个 JSON 对象（不要输出其它文字），包含以下 7 个字段：

- taskScore (0-100)：任务完成度——需求逐条是否达成，是否遗漏关键点。
- codeScore (0-100)：代码质量——可运行性、结构清晰、命名、错误处理、是否符合语言惯用法。
- testScore (0-100)：测试评分——是否附带测试、是否覆盖核心分支、是否真实通过。
- hallucinationRate (0-1)：幻觉率——产物/结论中无依据、编造、臆测内容的比例。
- confidence (0-100)：置信度——你对该评分的确定程度（证据是否充分）。
- overall (0-100)：综合评分。
- report (字符串)：一段不超过 200 字的中文评测报告摘要，点明主要优点与最关键的问题。

评分要求：
1. 每项分数必须有产物/过程证据支撑，禁止凭空打分。
2. 对「不确定」的结论，宁可降低 confidence，也不要编造事实。
3. hallucinationRate 越低越好（0 = 无幻觉，1 = 全为编造）。

仅输出 JSON：
{{"taskScore": 0, "codeScore": 0, "testScore": 0, "hallucinationRate": 0.0, "confidence": 0, "overall": 0, "report": "..."}}"""


__all__ = [
    "SEVEN_FIELDS",
    "EvaluationResult",
    "clamp_score",
    "clamp_rate",
    "compute_overall",
    "strip_think_blocks",
    "parse_judge_output",
    "build_prompt",
]
