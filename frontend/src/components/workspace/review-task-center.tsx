"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { evaluationApi } from "@/core/evaluation/api";
import {
  taskIdValid,
  taskMetadataMatches,
} from "@/core/evaluation/task-policy";
import type { ReviewTask, ReviewTaskPage } from "@/core/evaluation/task-types";

import { ReviewTaskDetail } from "./review-task-detail";

export function ReviewTaskCenter({ zh }: { zh: boolean }) {
  const [page, setPage] = useState<ReviewTaskPage | null>(null);
  const [selected, setSelected] = useState<ReviewTask | null>(null);
  const [taskId, setTaskId] = useState("");
  const [role, setRole] = useState("all");
  const [status, setStatus] = useState("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const epoch = useRef(0);
  const text = (cn: string, en: string) => (zh ? cn : en);
  const roleLabels = {
    owner: text("发起人", "Owner"),
    reviewer_1: text("盲审人 1", "Blind reviewer 1"),
    reviewer_2: text("盲审人 2", "Blind reviewer 2"),
    arbitrator: text("仲裁人", "Arbitrator"),
  };
  const statusLabels = {
    queued: text("待领取", "Queued"),
    in_review: text("复核中", "In review"),
    escalated: text("待仲裁 / 补证", "Escalated / needs evidence"),
    resolved: text("已有逐条结论", "Case resolved"),
    cancelled: text("已撤销", "Cancelled"),
  };
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  async function operate(action: () => Promise<ReviewTaskPage | ReviewTask>) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError("");
    setSelected(null);
    try {
      const data = await action();
      if (token === epoch.current) {
        if ("tasks" in data) {
          if (
            !Array.isArray(data.tasks) ||
            data.tasks.length > 50 ||
            data.limit !== 50 ||
            !Number.isInteger(data.offset) ||
            data.offset < 0 ||
            data.offset > 10_000 ||
            !data.tasks.every((row) => taskMetadataMatches(row, row.id))
          )
            throw new Error("Invalid task page");
          setPage(data);
        } else {
          if (!taskMetadataMatches(data, taskId))
            throw new Error("Task mismatch");
          setSelected(data);
        }
      }
    } catch {
      if (token === epoch.current)
        setError(
          text(
            "读取失败，请核对权限与任务 ID。不会自动重试。",
            "Read failed; check permissions and task ID. No automatic retry.",
          ),
        );
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  function load(offset: number) {
    return operate(() =>
      evaluationApi<ReviewTaskPage>(
        "evaluation/review-tasks?offset=" + offset + "&limit=50",
      ),
    );
  }
  const filtered =
    page?.tasks.filter(
      (task) =>
        (role === "all" || task.role === role) &&
        (status === "all" || task.status === status),
    ) ?? [];
  return (
    <div className="min-w-0 space-y-5">
      <p className="text-muted-foreground text-sm">
        {text(
          "跨项目显示我发起或被明确指派的独立逐条复核。列表只读元数据，证据必须领取后明确打开。不会自动加载敏感内容、通知、执行测试或调用模型；逐条结论尚未接入汇总、报告或正式验收。",
          "Cross-project independent case tasks you own or are explicitly assigned. Lists contain metadata only; claim before explicitly opening evidence. No automatic sensitive reads, notifications, execution or model calls. Resolutions are not yet integrated into summaries, reports or formal acceptance.",
        )}
      </p>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      <fieldset
        disabled={busy}
        className="min-w-0 space-y-4 rounded-xl border p-4"
      >
        <Button
          className="h-auto max-w-full text-left whitespace-normal"
          variant="outline"
          onClick={() => void load(0)}
        >
          {text("加载 / 刷新我的复核任务", "Load / refresh my review tasks")}
        </Button>
        <label className="block space-y-1 text-sm">
          <span>{text("按任务 ID 查找", "Look up task ID")}</span>
          <Input
            autoComplete="off"
            spellCheck={false}
            value={taskId}
            maxLength={32}
            onChange={(e) => {
              setTaskId(e.target.value);
              setSelected(null);
            }}
          />
        </label>
        <Button
          className="h-auto max-w-full text-left whitespace-normal"
          variant="outline"
          disabled={!taskIdValid(taskId)}
          onClick={() =>
            void operate(() =>
              evaluationApi<ReviewTask>("evaluation/review-tasks/" + taskId),
            )
          }
        >
          {text("按 ID 打开任务元数据", "Open task metadata by ID")}
        </Button>
        {page && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-3">
              <label className="space-y-1 text-sm">
                <span>{text("本页角色筛选", "Role filter (loaded page)")}</span>
                <select
                  className="bg-background block max-w-full rounded border p-2"
                  value={role}
                  onChange={(e) => {
                    setRole(e.target.value);
                    setSelected(null);
                  }}
                >
                  <option value="all">{text("全部角色", "All roles")}</option>
                  {Object.entries(roleLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm">
                <span>
                  {text("本页状态筛选", "Status filter (loaded page)")}
                </span>
                <select
                  className="bg-background block max-w-full rounded border p-2"
                  value={status}
                  onChange={(e) => {
                    setStatus(e.target.value);
                    setSelected(null);
                  }}
                >
                  <option value="all">
                    {text("全部状态", "All statuses")}
                  </option>
                  {Object.entries(statusLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="text-muted-foreground text-xs">
              {text(
                "筛选只作用于已加载页，不表示全部任务数量；列表不会自动轮询。",
                "Filters apply only to the loaded page, not global task counts; no automatic polling.",
              )}
            </p>
            <ul className="space-y-2">
              {filtered.map((task) => (
                <li key={task.id} className="rounded border p-3 text-sm">
                  <p className="break-all">
                    {task.project_id} · {task.run_id} · #{task.ordinal} ·{" "}
                    {roleLabels[task.role]} · {statusLabels[task.status]} ·{" "}
                    {text("轮次", "Round")} {task.round}
                  </p>
                  <Button
                    className="mt-2 h-auto max-w-full text-left break-all whitespace-normal"
                    variant="outline"
                    onClick={() => {
                      setSelected(task);
                      setTaskId(task.id);
                    }}
                  >
                    {text("打开任务", "Open task")} {task.id}
                  </Button>
                </li>
              ))}
            </ul>
            {!filtered.length && (
              <p role="status">
                {text(
                  "本页没有匹配任务。owner 可从项目样本复核页明确创建指派。",
                  "No matching tasks on this page. Owners can explicitly assign review from a project's case review panel.",
                )}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button
                className="h-auto max-w-full text-left whitespace-normal"
                variant="outline"
                disabled={page.offset === 0}
                onClick={() => void load(Math.max(0, page.offset - 50))}
              >
                {text("上一页任务", "Previous task page")}
              </Button>
              <span className="text-xs">
                {text("页偏移", "Page offset")}: {page.offset}
              </span>
              <Button
                className="h-auto max-w-full text-left whitespace-normal"
                variant="outline"
                disabled={page.tasks.length < 50 || page.offset + 50 > 10_000}
                onClick={() => void load(page.offset + 50)}
              >
                {text("下一页任务", "Next task page")}
              </Button>
            </div>
          </div>
        )}
      </fieldset>
      {selected && (
        <ReviewTaskDetail
          key={selected.id + ":" + selected.revision}
          initialTask={selected}
          zh={zh}
        />
      )}
    </div>
  );
}
