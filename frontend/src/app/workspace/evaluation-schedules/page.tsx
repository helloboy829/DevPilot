"use client";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ScheduledTaskScheduleInput,
  type ScheduleValue,
} from "@/components/workspace/scheduled-task-schedule-input";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useComponents } from "@/core/component-tests/hooks";
import { evaluationApi } from "@/core/evaluation/api";
import { useI18n } from "@/core/i18n/hooks";

interface Task {
  id: string;
  title: string;
  status: string;
  next_run_at: string | null;
  last_error: string | null;
  timezone: string;
  plan: {
    component_id: string;
    test_type: string;
    component_sha256: string;
    params: Record<string, unknown>;
  };
}
interface Catalog {
  enabled: boolean;
  tasks: Task[];
}
interface TaskRun {
  id: string;
  status: string;
  run_id: string | null;
  error: string | null;
  started_at: string | null;
}
const initialSchedule: ScheduleValue = {
  schedule_type: "cron",
  schedule_spec: { cron: "0 2 * * *" },
  timezone: "Asia/Shanghai",
};

export default function EvaluationSchedulesPage() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const { data } = useComponents();
  const components = data ?? [];
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [reload, setReload] = useState(0);
  const [title, setTitle] = useState("");
  const [component, setComponent] = useState("");
  const [type, setType] = useState("perf");
  const [params, setParams] = useState(
    '{"payload": {}, "max_requests": 20, "concurrency_levels": [1, 5]}',
  );
  const [schedule, setSchedule] = useState<ScheduleValue>(initialSchedule);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [runs, setRuns] = useState<TaskRun[] | null>(null);
  useEffect(() => {
    let active = true;
    void evaluationApi<Catalog>("evaluation-schedules")
      .then((c) => {
        if (active) setCatalog(c);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : "Load failed");
      });
    return () => {
      active = false;
    };
  }, [reload]);
  async function action(id: string, command: "pause" | "resume" | "delete") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await evaluationApi(
        "scheduled-tasks/" +
          encodeURIComponent(id) +
          (command === "delete" ? "" : "/" + command),
        command === "delete" ? undefined : {},
        command === "delete" ? "DELETE" : "POST",
      );
      setReload((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {zh ? "定时评测" : "Scheduled evaluations"}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody>
        <div className="mx-auto w-full max-w-5xl space-y-6 p-6">
          <p className="text-muted-foreground text-sm">
            {zh
              ? "用于错峰执行效果 / 性能测试，不运行抓取推送或自由聊天任务。保存时固定组件配置指纹与参数；目标、协议或验收规则改变后，原计划会拒绝执行，需重新确认。凭据从本人注册的组件读取，不放入计划。定时效果测试先采集结果、待人工复核，不自动把答案发给裁判模型。"
              : "Off-peak effect/performance evaluation, not scraping or chat automation. Plans pin component configuration and parameters; changes require a newly confirmed schedule. Credentials are read from your registered component, not stored in the plan. Scheduled effect runs collect outputs for manual review; answers are not automatically sent to a judge model."}
          </p>
          {catalog && !catalog.enabled && (
            <p role="status">
              {zh
                ? "调度器尚未启用，请管理员设置 scheduler.enabled。"
                : "Scheduler is disabled; ask the operator to enable scheduler.enabled."}
            </p>
          )}
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          <form
            className="space-y-4 rounded-xl border p-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (busy || !consent) return;
              setBusy(true);
              setError("");
              setConsent(false);
              let parsed: unknown;
              try {
                parsed = JSON.parse(params);
              } catch {
                setError(
                  zh ? "测试参数不是有效 JSON" : "Invalid JSON parameters",
                );
                setBusy(false);
                return;
              }
              void evaluationApi("evaluation-schedules", {
                title,
                component_id: component,
                test_type: type,
                params: parsed,
                ...schedule,
                consent: true,
              })
                .then(() => setReload((v) => v + 1))
                .catch((e: unknown) =>
                  setError(e instanceof Error ? e.message : "Save failed"),
                )
                .finally(() => setBusy(false));
            }}
          >
            <fieldset disabled={busy} className="space-y-3">
              <h2 className="font-semibold">
                {zh ? "创建评测计划" : "Create evaluation schedule"}
              </h2>
              <label className="block text-sm">
                {zh ? "计划名称" : "Title"}
                <Input
                  required
                  maxLength={200}
                  value={title}
                  onChange={(e) => {
                    setTitle(e.target.value);
                    setConsent(false);
                  }}
                />
              </label>
              <label className="block text-sm">
                {zh ? "已注册组件" : "Registered component"}
                <select
                  required
                  className="mt-1 block w-full rounded border p-2"
                  aria-label={
                    zh
                      ? "\u5df2\u767b\u8bb0\u7ec4\u4ef6"
                      : "Registered component"
                  }
                  value={component}
                  onChange={(e) => {
                    setComponent(e.target.value);
                    setConsent(false);
                  }}
                >
                  <option value="">
                    {zh ? "请选择组件" : "Select a component"}
                  </option>
                  {components
                    .filter((c) => c.enabled)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                </select>
              </label>
              <label className="block text-sm">
                {zh ? "测试类型" : "Test type"}
                <select
                  className="mt-1 block w-full rounded border p-2"
                  value={type}
                  onChange={(e) => {
                    setType(e.target.value);
                    setParams(
                      e.target.value === "perf"
                        ? '{"payload": {}, "max_requests": 20, "concurrency_levels": [1, 5]}'
                        : '{"samples": []}',
                    );
                    setConsent(false);
                  }}
                >
                  <option value="effect">{zh ? "效果测试" : "Effect"}</option>
                  <option value="perf">
                    {zh ? "性能测试" : "Performance"}
                  </option>
                </select>
              </label>
              <ScheduledTaskScheduleInput
                initial={initialSchedule}
                onChange={(value) => {
                  setSchedule(value);
                  setConsent(false);
                }}
              />
              <label className="block text-sm">
                {zh
                  ? "测试参数 JSON（效果须填写非空样本；性能最多 1000 请求/档、20 并发）"
                  : "JSON parameters (nonempty effect samples; max 1000 requests/level, concurrency 20)"}
                <Textarea
                  rows={6}
                  value={params}
                  onChange={(e) => {
                    setParams(e.target.value);
                    setConsent(false);
                  }}
                />
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />
                {zh
                  ? "我确认测试范围、样本、负载与时区，授权系统按此计划调用接口。目标必须在管理员出站白名单内。重复任务上一轮未完成时跳过，不补发错过的负载。"
                  : "I authorize this test scope, data, load and timezone against an operator-approved host. Overlapping occurrences are skipped; missed load is not replayed."}
              </label>
              <Button
                type="submit"
                disabled={busy || !consent || !catalog?.enabled || !component}
              >
                {zh ? "确认并保存计划" : "Confirm and save schedule"}
              </Button>
            </fieldset>
          </form>
          <section className="space-y-3">
            <div className="flex justify-between">
              <h2 className="font-semibold">
                {zh ? "计划与执行历史" : "Schedules and history"}
              </h2>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setReload((v) => v + 1)}
              >
                {zh ? "刷新" : "Refresh"}
              </Button>
            </div>
            {catalog?.tasks.length === 0 && (
              <p>{zh ? "暂无评测计划" : "No evaluation schedules"}</p>
            )}
            {catalog?.tasks.map((task) => (
              <article
                key={task.id}
                className="space-y-2 rounded-xl border p-4"
              >
                <div className="flex flex-wrap justify-between gap-2">
                  <strong>{task.title}</strong>
                  <span>
                    {task.status} · {task.plan.test_type}
                  </span>
                </div>
                <p className="text-sm">
                  {components.find((c) => c.id === task.plan.component_id)
                    ?.name ?? task.plan.component_id}{" "}
                  · {task.timezone} · {zh ? "下次" : "Next"}:{" "}
                  {task.next_run_at
                    ? new Date(task.next_run_at).toLocaleString(locale)
                    : "—"}
                </p>
                {task.last_error && (
                  <p className="text-destructive text-sm">{task.last_error}</p>
                )}
                <details>
                  <summary className="text-sm">
                    {zh ? "查看固定参数" : "View frozen parameters"}
                  </summary>
                  <pre className="overflow-auto text-xs">
                    {JSON.stringify(task.plan, null, 2)}
                  </pre>
                </details>
                <div className="flex flex-wrap gap-2">
                  <Button
                    disabled={
                      busy || !["enabled", "paused"].includes(task.status)
                    }
                    variant="outline"
                    onClick={() =>
                      void action(
                        task.id,
                        task.status === "paused" ? "resume" : "pause",
                      )
                    }
                  >
                    {task.status === "paused"
                      ? zh
                        ? "恢复"
                        : "Resume"
                      : zh
                        ? "暂停后续运行"
                        : "Pause future runs"}
                  </Button>
                  <Button
                    disabled={busy}
                    variant="outline"
                    onClick={() => {
                      if (
                        window.confirm(
                          zh
                            ? "删除计划？不会中止已经开始的运行。"
                            : "Delete schedule? Active runs will not be stopped.",
                        )
                      )
                        void action(task.id, "delete");
                    }}
                  >
                    {zh ? "删除" : "Delete"}
                  </Button>
                  <Button
                    disabled={busy}
                    variant="outline"
                    onClick={() => {
                      void evaluationApi<TaskRun[]>(
                        "scheduled-tasks/" +
                          encodeURIComponent(task.id) +
                          "/runs",
                      )
                        .then(setRuns)
                        .catch((e: unknown) =>
                          setError(
                            e instanceof Error ? e.message : "History failed",
                          ),
                        );
                    }}
                  >
                    {zh ? "查看执行历史" : "Run history"}
                  </Button>
                </div>
              </article>
            ))}
          </section>
          {runs && (
            <section className="space-y-2 rounded border p-4">
              <h2>{zh ? "最近执行记录" : "Recent runs"}</h2>
              {runs.length === 0 && (
                <p>{zh ? "尚未执行" : "Not executed yet"}</p>
              )}
              {runs.map((run) => (
                <p key={run.id} className="text-sm">
                  {run.started_at} · {run.status} · {run.run_id} {run.error}
                </p>
              ))}
              <Button variant="ghost" onClick={() => setRuns(null)}>
                {zh ? "关闭" : "Close"}
              </Button>
            </section>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
