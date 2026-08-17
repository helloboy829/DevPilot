"""后台执行 AI 组件效果/性能测试（轻量 in-process 模型）。

状态翻转约定照 ``app/mcp_tasks`` / ``app/scheduler``：queued → running →
completed / failed。执行与评估分离：raw 原始返回落盘到
``{user_dir}/component-tests/{run_id}/raw.json``，完整报告写到同目录
``report.json``，摘要写回 ``component_test_runs.result``，便于反复重评。

MVP 用 ``asyncio.create_task`` + ``asyncio.Semaphore`` 限并发，不引入 lease
轮询（M8 再硬化）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from devpilot.toolkit.effect import effect_eval, effect_run
from devpilot.toolkit.perf import perf_eval, perf_run
from devpilot.toolkit.report import build_component_test_report, build_run_summary
from devpilot.toolkit.transports import TransportConfig

from deerflow.config.paths import get_paths, make_safe_user_id

logger = logging.getLogger(__name__)

COMPONENT_TESTS_DIRNAME = "component-tests"


class ComponentTestService:
    """在请求路径之外执行已注册 AI 组件的效果/性能测试。"""

    def __init__(self, *, component_repo, run_repo, max_concurrent: int = 2) -> None:
        self._component_repo = component_repo
        self._run_repo = run_repo
        self._sem = asyncio.Semaphore(max_concurrent)
        self._tasks: set[asyncio.Task] = set()

    def enqueue(self, *, run_id: str, user_id: str, component: dict[str, Any], test_type: str, params: dict[str, Any]) -> None:
        """把一次已建行（status=queued）的运行交给后台任务，立即返回。"""
        task = asyncio.create_task(
            self._execute(run_id=run_id, user_id=user_id, component=component, test_type=test_type, params=params),
            name=f"component-test-{run_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _run_dir(self, user_id: str, run_id: str) -> Path:
        safe_user_id = make_safe_user_id(user_id)
        return get_paths().user_dir(safe_user_id) / COMPONENT_TESTS_DIRNAME / run_id

    @staticmethod
    def _build_config(component: dict[str, Any], params: dict[str, Any]) -> TransportConfig:
        return TransportConfig(
            transport=component["transport"],
            api_url=component["api_url"],
            api_token=component.get("api_token"),
            response_mode=component.get("response_mode") or "blocking",
            headers=dict(params.get("headers") or {}),
            model=params.get("model"),
            timeout_seconds=float(params.get("timeout_seconds") or 30.0),
        )

    async def _execute(self, *, run_id: str, user_id: str, component: dict[str, Any], test_type: str, params: dict[str, Any]) -> None:
        async with self._sem:
            await self._run_repo.update(
                run_id,
                user_id=user_id,
                updates={"status": "running", "started_at": datetime.now(UTC), "error": None},
            )
            config = self._build_config(component, params)
            client = httpx.AsyncClient(
                trust_env=False,
                verify=False,
                timeout=httpx.Timeout(config.timeout_seconds),
            )
            try:
                criteria = component.get("acceptance_criteria") or {}
                if test_type == "effect":
                    samples = list(params.get("samples") or [])
                    results = await effect_run(config, samples, client=client)
                    report = await effect_eval(
                        results,
                        validation_type=component.get("validation_type") or "reference_text",
                        samples=samples,
                        criteria=criteria,
                        model_name=params.get("judge_model"),
                    )
                    raw_payload: dict[str, Any] = {"test_type": "effect", "results": [asdict(r) for r in results]}
                    full_report = build_component_test_report(component, test_type="effect", params=params, effect_report=report)
                    summary = build_run_summary(component, test_type="effect", effect_report=report)
                else:  # perf
                    payload = dict(params.get("payload") or {})
                    levels = await perf_run(
                        config,
                        payload,
                        concurrency_levels=list(params.get("concurrency_levels") or [1, 5, 10, 20]),
                        max_requests=int(params.get("max_requests") or 100),
                        duration_seconds=params.get("duration_seconds"),
                        client=client,
                    )
                    report = perf_eval(levels, criteria=criteria)
                    raw_payload = {"test_type": "perf", "levels": [lv.to_dict() for lv in levels]}
                    full_report = build_component_test_report(component, test_type="perf", params=params, perf_report=report)
                    summary = build_run_summary(component, test_type="perf", perf_report=report)

                raw_path = await self._persist(user_id, run_id, raw_payload, full_report)
                await self._run_repo.update(
                    run_id,
                    user_id=user_id,
                    updates={
                        "status": "completed",
                        "result": summary,
                        "raw_path": str(raw_path),
                        "completed_at": datetime.now(UTC),
                    },
                )
            except Exception as exc:
                logger.exception("Component test failed (run_id=%s)", run_id)
                await self._run_repo.update(
                    run_id,
                    user_id=user_id,
                    updates={
                        "status": "failed",
                        "error": str(exc) or type(exc).__name__,
                        "completed_at": datetime.now(UTC),
                    },
                )
            finally:
                await client.aclose()

    async def _persist(self, user_id: str, run_id: str, raw_payload: dict[str, Any], full_report: dict[str, Any]) -> Path:
        run_dir = self._run_dir(user_id, run_id)
        raw_path = run_dir / "raw.json"
        report_path = run_dir / "report.json"
        await asyncio.to_thread(self._write_json, raw_path, raw_payload)
        await asyncio.to_thread(self._write_json, report_path, full_report)
        return raw_path

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")

    async def stop(self) -> None:
        """等待在飞任务结束（有界），随后取消仍未完成的。"""
        tasks = list(self._tasks)
        if not tasks:
            return
        done, pending = await asyncio.wait(tasks, timeout=5.0)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
