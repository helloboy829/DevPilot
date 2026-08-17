"""评测体系挂载点：DeerFlow 任务生命周期扩展（post-run 自动评测）。

通过 ``config.yaml -> plugins:`` 加载（官方扩展机制，**不改核心代码**）：

    plugins:
      - module: devpilot.evaluation.extension
        enabled: true
        model: deepseek-v4        # 可选，评测用模型名
        requirement: "..."        # 可选，静态任务需求（覆盖自动探测）

在**主智能体（lead）任务完成后**（``on_task_stop``、``outcome=COMPLETED``），
本扩展收集该线程工作区产物 → 调用 LLM-as-Judge → 把 7 字段报告写入
``outputs/evaluation/<run_id>.json``。

设计原则：
    * **fail-open**：任何异常只记日志、不阻断研发主流程；
    * 评测结果只写 ``outputs/``（用户可见产物目录），不触碰 checkpoint/核心状态；
    * 需求来源按优先级：插件 config ``requirement`` > 工作区 ``task-requirement.txt``
      > 占位文本（置信度会自然降低）。基于 transcript 的需求自动抽取留作后续增强。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPORT_SUBDIR = "evaluation"


class _EvaluationContributor:
    """在 lead 任务完成后触发评测的 TaskLifecycleContributor 实现。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self._model: str | None = config.get("model")
        self._static_requirement: str = config.get("requirement", "") or ""

    async def on_task_start(self, app_store: Any, task_store: Any, info: Any) -> None:
        return None

    async def on_task_stop(self, app_store: Any, task_store: Any, info: Any, outcome: Any) -> None:
        # 只评测成功完成的 lead 任务；子任务/失败/中断不触发。
        if getattr(info, "kind", None) != "lead":
            return
        if getattr(outcome, "value", str(outcome)) != "completed":
            return

        thread_id = getattr(info, "thread_id", None)
        run_id = getattr(info, "run_id", None)
        if not thread_id or not run_id:
            return

        try:
            await self._evaluate(thread_id, run_id)
        except Exception:  # noqa: BLE001 - fail-open
            logger.exception("DevPilot 评测扩展执行失败（thread=%s run=%s）", thread_id, run_id)

    async def _evaluate(self, thread_id: str, run_id: str) -> None:
        # 惰性 import deerflow，避免加载扩展时拖慢启动。
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import get_effective_user_id

        from devpilot.evaluation.cli import collect_artifacts
        from devpilot.evaluation.runner import judge_with_model

        user_id = get_effective_user_id()
        paths = get_paths()
        workspace = Path(paths.sandbox_work_dir(thread_id, user_id=user_id))
        outputs = Path(paths.sandbox_outputs_dir(thread_id, user_id=user_id))

        if not workspace.is_dir():
            logger.info("DevPilot 评测：线程 %s 无工作区，跳过", thread_id)
            return

        artifacts = collect_artifacts(workspace)
        if not artifacts:
            logger.info("DevPilot 评测：线程 %s 无文本产物，跳过", thread_id)
            return

        requirement = self._static_requirement or self._read_requirement_file(workspace)

        result = await judge_with_model(
            requirement=requirement,
            artifacts=artifacts,
            model_name=self._model,
        )

        report_dir = outputs / _REPORT_SUBDIR
        report_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "evaluation": result.to_dict(),
            "meta": {
                "thread_id": thread_id,
                "run_id": run_id,
                "artifact_count": len(artifacts),
                "artifact_names": list(artifacts.keys()),
                "model": self._model or "(config default)",
            },
        }
        report_path = report_dir / f"{run_id}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("DevPilot 评测完成：%s", report_path)

    @staticmethod
    def _read_requirement_file(workspace: Path) -> str:
        for name in ("task-requirement.txt", "requirement.txt"):
            path = workspace / name
            if path.is_file():
                try:
                    return path.read_text(encoding="utf-8", errors="replace")[:2000]
                except OSError:
                    continue
        return "（未提供需求文本）"


def install(registry: Any, config: Mapping[str, Any]) -> None:
    """扩展入口（签名符合 ``ExtensionInstall`` 契约）。"""
    if not config.get("enabled", False):
        return
    registry.task_lifecycle(_EvaluationContributor(config))


__all__ = ["install", "_EvaluationContributor"]
