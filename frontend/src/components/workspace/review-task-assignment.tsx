"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { evaluationApi } from "@/core/evaluation/api";
import type { ReviewCase } from "@/core/evaluation/review-types";
import {
  buildTaskCreate,
  taskActorsValid,
  taskReceiptMatches,
} from "@/core/evaluation/task-policy";
import type {
  PendingReviewTask,
  PendingReviewTasks,
  ReviewTask,
} from "@/core/evaluation/task-types";

import { ReviewTaskDetail } from "./review-task-detail";

export function ReviewTaskAssignment({
  projectId,
  caseData,
  pendingTasks,
  zh,
}: {
  projectId: string;
  caseData: ReviewCase;
  pendingTasks: PendingReviewTasks;
  zh: boolean;
}) {
  const key = projectId + ":" + caseData.run_id + ":" + caseData.ordinal;
  const [receipt, setReceipt] = useState<PendingReviewTask | undefined>(() =>
    pendingTasks.get(key),
  );
  const [actors, setActors] = useState<[string, string, string]>(["", "", ""]);
  const [share, setShare] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const lock = useRef(false);
  const epoch = useRef(0);
  const text = (cn: string, en: string) => (zh ? cn : en);
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  async function operate(reconcile: boolean) {
    if (
      lock.current ||
      (!reconcile &&
        (!share || !confirmed || receipt || !taskActorsValid(actors)))
    )
      return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError("");
    setConfirmed(false);
    setShare(false);
    try {
      const current = reconcile
        ? receipt
        : {
            id: crypto.randomUUID().replaceAll("-", ""),
            projectId,
            payload: buildTaskCreate(caseData, actors),
          };
      if (!current) return;
      // Persist BEFORE sending. Never auto-resend, even when a receipt GET returns 404.
      pendingTasks.set(key, current);
      setReceipt(current);
      const data = reconcile
        ? await evaluationApi<ReviewTask>(
            "evaluation/review-tasks/" + current.id,
          )
        : await evaluationApi<ReviewTask>(
            "evaluation/projects/" +
              encodeURIComponent(projectId) +
              "/review-tasks/" +
              current.id,
            current.payload,
          );
      if (!taskReceiptMatches(data, current))
        throw new Error("Receipt mismatch");
      const verified = { ...current, task: data };
      pendingTasks.set(key, verified);
      if (token === epoch.current) setReceipt(verified);
    } catch {
      if (token === epoch.current)
        setError(
          text(
            "创建结果未确认。请记录同一任务 ID，仅用 GET 核对，不要重复创建。404 也不能证明延迟写入绝未发生。",
            "Creation unconfirmed. Record the same task ID and reconcile by GET only; do not recreate. Even 404 does not prove a delayed write never happened.",
          ),
        );
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  return (
    <section
      className="min-w-0 space-y-4 rounded-xl border p-4"
      aria-label={text("分配独立逐条复核", "Assign independent case review")}
    >
      <h3 className="font-semibold">
        {text("分配独立逐条复核", "Assign independent case review")}
      </h3>
      <p className="text-muted-foreground text-sm">
        {text(
          "明确分享本冻结样本的输入、实际输出、参考答案与来源。两名不同盲审人及第三名仲裁人均不能是 owner。只授予此任务，不授予项目成员或普通数据访问权；不会自动通知。",
          "Explicitly share this frozen case's input, output, reference and source. Two distinct blind reviewers and a third arbitrator must all differ from the owner. This grants only the task, not project membership or general data access; no automatic notification.",
        )}
      </p>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {receipt ? (
        <div className="min-w-0 space-y-3">
          <p className="text-sm break-all">
            {text("任务 ID", "Task ID")}: {receipt.id}
          </p>
          <p role="status" className="text-sm">
            {receipt.task
              ? text(
                  "已确认任务回执。逐条结论不是正式批准。",
                  "Task receipt confirmed. A case resolution is not formal approval.",
                )
              : text(
                  "待核对写入；不会再次发送创建请求。切换项目仍保留 ID；离开或刷新整页前请记录 ID，以便在复核中心核对。",
                  "Pending reconciliation; creation will not be resent. The ID survives project switches. Record it before leaving or reloading this page so you can reconcile in the review center.",
                )}
          </p>
          <Button
            className="h-auto max-w-full text-left whitespace-normal"
            variant="outline"
            disabled={busy}
            onClick={() => void operate(true)}
          >
            {text("按同一 ID 核对任务（GET）", "Reconcile same task ID (GET)")}
          </Button>
          <Link
            href="/workspace/reviews"
            className="text-primary block text-sm underline"
          >
            {text(
              "前往复核中心，按任务 ID 打开",
              "Open review center and look up the task ID",
            )}
          </Link>
          {receipt.task && (
            <ReviewTaskDetail
              key={receipt.task.id + ":" + receipt.task.revision}
              initialTask={receipt.task}
              zh={zh}
            />
          )}
        </div>
      ) : (
        <fieldset disabled={busy} className="space-y-3">
          {actors.map((id, index) => (
            <label key={index} className="block space-y-1 text-sm">
              <span>
                {index === 2
                  ? text("仲裁人账号 ID", "Arbitrator account ID")
                  : text("盲审人", "Blind reviewer") +
                    " " +
                    (index + 1) +
                    text(" 账号 ID", " account ID")}
              </span>
              <Input
                value={id}
                maxLength={36}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => {
                  const next: [string, string, string] = [...actors];
                  next[index] = e.target.value;
                  setActors(next);
                  setShare(false);
                  setConfirmed(false);
                }}
              />
            </label>
          ))}
          <p className="text-muted-foreground text-xs">
            {text(
              "仅接受已完成设置账号的规范小写 UUID，无人员目录查询。请通过获准渠道取得准确 ID。",
              "Canonical lowercase UUIDs of ready accounts only; no account directory lookup. Obtain exact IDs through an authorized channel.",
            )}
          </p>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={share}
              onChange={(e) => {
                setShare(e.target.checked);
                setConfirmed(false);
              }}
            />
            {text(
              "我有权向这三人分享本样本参考答案及相关敏感证据。",
              "I am authorized to share this case's reference and sensitive evidence with these three people.",
            )}
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            {text(
              "我明确确认创建本冻结样本的独立复核任务，不是正式批准。",
              "I explicitly confirm creating independent review for this frozen case, not formal approval.",
            )}
          </label>
          <Button
            className="h-auto max-w-full text-left whitespace-normal"
            disabled={!share || !confirmed || !taskActorsValid(actors)}
            onClick={() => void operate(false)}
          >
            {text("创建独立复核任务", "Create independent review task")}
          </Button>
        </fieldset>
      )}
    </section>
  );
}
