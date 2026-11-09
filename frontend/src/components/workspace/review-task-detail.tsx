"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { evaluationApi } from "@/core/evaluation/api";
import type { ReviewDecision } from "@/core/evaluation/review-types";
import {
  taskCanPass,
  taskCaseMatches,
  taskLeaseActive,
  taskMetadataMatches,
  taskPhaseAllowed,
} from "@/core/evaluation/task-policy";
import type {
  ReviewTask,
  TaskCase,
  TaskResult,
} from "@/core/evaluation/task-types";

/** Shared by the cross-project inbox and the owner's inline case assignment. */
export function ReviewTaskDetail({
  initialTask,
  zh,
}: {
  initialTask: ReviewTask;
  zh: boolean;
}) {
  const [task, setTask] = useState(initialTask);
  const [opened, setOpened] = useState<TaskCase | null>(null);
  const [result, setResult] = useState<TaskResult | null>(null);
  const [round, setRound] = useState(String(initialTask.round));
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState<ReviewDecision>("uncertain");
  const [confirmed, setConfirmed] = useState(false);
  const [actionConfirmed, setActionConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [, tickLease] = useState(0);
  const lock = useRef(false);
  const epoch = useRef(0);
  const root = "evaluation/review-tasks/" + task.id;
  const text = (cn: string, en: string) => (zh ? cn : en);
  const owner = task.role === "owner";
  const active = taskLeaseActive(task);
  const phase = taskPhaseAllowed(task);
  const writable = !busy && !needsRefresh;
  const labels = {
    pass: text("通过", "Pass"),
    fail: text("不通过", "Fail"),
    uncertain: text("资料不足 / 不确定", "Insufficient / uncertain"),
  };
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  useEffect(() => {
    const until = task.assignment?.lease_until_ms;
    if (until && until > Date.now()) {
      const timer = setTimeout(
        () => {
          setConfirmed(false);
          setOpened(null);
          tickLease((n) => n + 1);
        },
        Math.min(until - Date.now() + 1, 1_800_001),
      );
      return () => clearTimeout(timer);
    }
  }, [task]);
  function revoke() {
    setConfirmed(false);
    setActionConfirmed(false);
    setNotice("");
  }
  function accept(data: ReviewTask) {
    if (
      !taskMetadataMatches(data, task.id) ||
      data.subject_hash !== task.subject_hash ||
      data.project_id !== task.project_id ||
      data.case_hash !== task.case_hash ||
      data.run_id !== task.run_id ||
      data.ordinal !== task.ordinal ||
      data.role !== task.role
    )
      throw new Error("Task mismatch");
    if (data.round !== task.round) {
      setNote("");
      setReason("");
      setDecision("uncertain");
      setRound(String(data.round));
    }
    setTask(data);
    setOpened(null);
    setResult(null);
  }
  async function operate(
    action: (token: number) => Promise<void>,
    writing = false,
  ) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError("");
    revoke();
    try {
      await action(token);
    } catch {
      if (token === epoch.current) {
        setOpened(null);
        setResult(null);
        if (writing) setNeedsRefresh(true);
        setError(
          text(
            "操作未确认成功。保留草稿；请按同一任务 ID 刷新核对，不会自动重发。权限、版本或租约变化也会拒绝操作。",
            "Operation unconfirmed. Draft retained; refresh this same task ID to reconcile. No automatic resend. Permission, revision or lease changes may also reject the action.",
          ),
        );
      }
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  async function refresh(token: number) {
    setOpened(null);
    setResult(null);
    const data = await evaluationApi<ReviewTask>(root);
    if (token === epoch.current) {
      accept(data);
      setNeedsRefresh(false);
      setNotice(
        text(
          "已核对当前元数据。提交前须重新打开当前证据并明确确认。",
          "Current metadata checked. Reopen current evidence and explicitly confirm before submitting.",
        ),
      );
    }
  }
  async function command(
    action: "claim" | "release" | "cancel" | "reopen",
    token: number,
  ) {
    if (!actionConfirmed || needsRefresh) return;
    const data = await evaluationApi<ReviewTask>(root + "/" + action, {
      expected_revision: task.revision,
      confirmed: true,
      ...(action === "reopen" ? { reason } : {}),
    });
    if (token === epoch.current) {
      accept(data);
      setNeedsRefresh(false);
      setNotice(
        text(
          "任务操作已确认；请按需重新打开证据。",
          "Task action confirmed; explicitly reopen evidence as needed.",
        ),
      );
    }
  }
  async function openCase(token: number) {
    setOpened(null);
    setResult(null);
    const data = await evaluationApi<TaskCase>(root + "/case");
    if (token === epoch.current) {
      if (
        !taskCaseMatches(data, task) ||
        !taskLeaseActive(task) ||
        !taskPhaseAllowed(task)
      )
        throw new Error("Case mismatch or expired lease");
      setOpened(data);
    }
  }
  async function submit(token: number) {
    if (
      !opened ||
      !confirmed ||
      needsRefresh ||
      !taskLeaseActive(task) ||
      !taskCaseMatches(opened, task) ||
      !note.trim() ||
      (decision === "pass" && !taskCanPass(opened))
    )
      return;
    const data = await evaluationApi<ReviewTask>(root + "/decisions", {
      expected_revision: opened.task_revision,
      subject_hash: opened.subject_hash,
      decision,
      note,
      confirmed: true,
    });
    if (token === epoch.current) {
      accept(data);
      setNote("");
      setDecision("uncertain");
      setNotice(
        text(
          "已追加不可变人工决定。逐条结论不是正式验收批准。",
          "Immutable human decision appended. A case resolution is not formal acceptance.",
        ),
      );
    }
  }
  async function openResult(token: number) {
    setOpened(null);
    setResult(null);
    const n = Number(round);
    if (!Number.isInteger(n) || n < 1 || n > task.round) return;
    const data = await evaluationApi<TaskResult>(
      root + "/result?round_number=" + n,
    );
    if (token === epoch.current) {
      if (
        data.task_id !== task.id ||
        data.round !== n ||
        data.resolution.task_id !== task.id ||
        data.resolution.round !== n ||
        data.resolution.subject_hash !== task.subject_hash ||
        data.resolution.scope !== "case_resolution_only" ||
        data.resolution.approval !== "not_approved"
      )
        throw new Error("Result mismatch");
      setResult(data);
    }
  }
  const selectedRound = Number(round);
  return (
    <section
      className="min-w-0 space-y-4 rounded-xl border p-4"
      aria-label={text("独立复核任务详情", "Independent review task detail")}
    >
      <h3 className="font-semibold">
        {text("独立复核任务", "Independent review task")}
      </h3>
      <p className="text-sm break-all">
        {task.id} · {task.role} · {task.status} · {text("轮次", "Round")}{" "}
        {task.round} · r{task.revision}
      </p>
      <p className="text-muted-foreground text-sm">
        {text(
          "双盲逐条复核，不是正式批准。不会启动执行或调用模型。复核人看不到 owner 或另一复核人的意见；仲裁阶段才展示两份盲审决定。",
          "Double-blind case review, not formal approval. No execution or model calls. Reviewers cannot see the owner or peer's decisions; only arbitration reveals the two blind decisions.",
        )}
      </p>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {needsRefresh && (
        <p role="status">
          {text(
            "写入结果未知：请仅刷新此任务，不要重复提交。",
            "Write outcome unknown: refresh this task only; do not resend.",
          )}
        </p>
      )}
      <fieldset disabled={busy} className="min-w-0 space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button
            className="h-auto max-w-full text-left whitespace-normal"
            variant="outline"
            onClick={() => void operate(refresh)}
          >
            {text("刷新任务元数据", "Refresh task metadata")}
          </Button>
          <Button
            className="h-auto max-w-full text-left whitespace-normal"
            variant="outline"
            onClick={() => {
              setOpened(null);
              setResult(null);
              revoke();
            }}
          >
            {text("关闭敏感内容", "Close sensitive content")}
          </Button>
        </div>
        {task.assignments && owner && (
          <ul className="space-y-1 text-sm">
            {task.assignments.map((a) => (
              <li key={a.role} className="break-all">
                {a.role} · {a.actor_id} · {a.status}
              </li>
            ))}
          </ul>
        )}
        {task.assignment && (
          <p className="text-sm">
            {text("我的领取状态", "My assignment")}: {task.assignment.status}
            {task.assignment.lease_until_ms !== null && (
              <>
                {" "}
                · {text("租约截止", "Lease until")}{" "}
                {new Date(task.assignment.lease_until_ms).toLocaleString()}{" "}
                {!active && text("（当前无有效租约）", "(no active lease)")}
              </>
            )}
          </p>
        )}
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={actionConfirmed}
            disabled={!writable}
            onChange={(e) => setActionConfirmed(e.target.checked)}
          />
          {text(
            "我明确确认下一次领取、释放、撤销或重开操作。",
            "I explicitly confirm the next claim, release, cancel or reopen action.",
          )}
        </label>
        {!owner && (
          <div className="flex flex-wrap gap-2">
            <Button
              className="h-auto max-w-full text-left whitespace-normal"
              disabled={
                !writable ||
                !actionConfirmed ||
                !phase ||
                active ||
                task.assignment?.status === "submitted"
              }
              onClick={() => void operate((n) => command("claim", n), true)}
            >
              {text("领取任务（30 分钟）", "Claim task (30 minutes)")}
            </Button>
            <Button
              className="h-auto max-w-full text-left whitespace-normal"
              variant="outline"
              disabled={!writable || !actionConfirmed || !active || !phase}
              onClick={() => void operate((n) => command("release", n), true)}
            >
              {text("释放领取", "Release claim")}
            </Button>
            <Button
              className="h-auto max-w-full text-left whitespace-normal"
              variant="outline"
              disabled={!writable || !active || !phase}
              onClick={() => void operate(openCase)}
            >
              {text(
                "明确打开输入、输出与参考",
                "Explicitly open input, output & reference",
              )}
            </Button>
          </div>
        )}
        {owner && (
          <div className="min-w-0 space-y-3">
            <Button
              className="h-auto max-w-full text-left whitespace-normal"
              variant="outline"
              disabled={
                !writable || !actionConfirmed || task.status === "cancelled"
              }
              onClick={() => void operate((n) => command("cancel", n), true)}
            >
              {text("撤销任务授权", "Cancel task grant")}
            </Button>
            <label className="block space-y-1 text-sm">
              <span>{text("重开原因", "Reopen reason")}</span>
              <Textarea
                value={reason}
                maxLength={2000}
                onChange={(e) => {
                  setReason(e.target.value);
                  revoke();
                }}
              />
            </label>
            <Button
              className="h-auto max-w-full text-left whitespace-normal"
              variant="outline"
              disabled={
                !writable ||
                !actionConfirmed ||
                !reason.trim() ||
                task.round >= 10 ||
                !["resolved", "escalated"].includes(task.status)
              }
              onClick={() => void operate((n) => command("reopen", n), true)}
            >
              {text(
                "新增复核轮次（保留历史）",
                "Reopen in a new round (retain history)",
              )}
            </Button>
            <label className="block space-y-1 text-sm">
              <span>{text("查看结论轮次", "Result round")}</span>
              <input
                className="bg-background w-full max-w-xs rounded border p-2"
                type="number"
                min={1}
                max={task.round}
                value={round}
                onChange={(e) => {
                  setRound(e.target.value);
                  setResult(null);
                  revoke();
                }}
              />
            </label>
            <Button
              className="h-auto max-w-full text-left whitespace-normal"
              variant="outline"
              disabled={
                !Number.isInteger(selectedRound) ||
                selectedRound < 1 ||
                selectedRound > task.round
              }
              onClick={() => void operate(openResult)}
            >
              {text(
                "明确打开该轮结论与理由",
                "Explicitly open round result & reasons",
              )}
            </Button>
          </div>
        )}
        {opened && (
          <div className="space-y-4">
            <p className="text-sm">
              {opened.component_name} · {opened.plan_label} · {opened.sample_id}{" "}
              · {opened.state} · {opened.technical.kind ?? "—"} · HTTP{" "}
              {opened.technical.http_status ?? "—"}
            </p>
            <dl className="space-y-2 text-sm">
              <dt>{text("测试输入", "Test input")}</dt>
              <dd>
                <pre
                  tabIndex={0}
                  className="max-h-96 overflow-auto rounded border p-3 break-words whitespace-pre-wrap"
                >
                  {opened.input}
                </pre>
              </dd>
              <dt>{text("实际输出", "Actual output")}</dt>
              <dd>
                <pre
                  tabIndex={0}
                  className="max-h-96 overflow-auto rounded border p-3 break-words whitespace-pre-wrap"
                >
                  {opened.output ?? text("没有输出证据", "No output evidence")}
                </pre>
              </dd>
              <dt>{text("参考答案", "Reference answer")}</dt>
              <dd>
                <pre
                  tabIndex={0}
                  className="max-h-96 overflow-auto rounded border p-3 break-words whitespace-pre-wrap"
                >
                  {opened.expected}
                </pre>
              </dd>
              <dt>
                {text(
                  "来源（仅文本，不自动打开）",
                  "Source (text only; never auto-opened)",
                )}
              </dt>
              <dd className="break-all">{opened.source_ref}</dd>
              <dt>{text("数据分层", "Slice")}</dt>
              <dd>{opened.slice_tag}</dd>
            </dl>
            {task.role === "arbitrator" && (
              <section
                aria-label={text(
                  "盲审决定（仅仲裁）",
                  "Blind decisions (arbitration only)",
                )}
                className="space-y-2"
              >
                <h4>{text("两份盲审决定", "Two blind decisions")}</h4>
                {opened.prior_decisions.map((d) => (
                  <div key={d.role} className="rounded border p-3 text-sm">
                    <p>
                      {d.role} · {labels[d.decision]}
                    </p>
                    <pre
                      tabIndex={0}
                      className="max-h-64 overflow-auto break-words whitespace-pre-wrap"
                    >
                      {d.note}
                    </pre>
                  </div>
                ))}
              </section>
            )}
            <fieldset
              disabled={!writable || !active || !phase}
              className="space-y-3"
            >
              <legend>
                {text("追加独立人工决定", "Append independent human decision")}
              </legend>
              <div className="flex flex-wrap gap-4">
                {(["pass", "fail", "uncertain"] as const).map((v) => (
                  <label key={v} className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name={"task-decision-" + task.id}
                      checked={decision === v}
                      disabled={v === "pass" && !taskCanPass(opened)}
                      onChange={() => {
                        setDecision(v);
                        revoke();
                      }}
                    />
                    {labels[v]}
                  </label>
                ))}
              </div>
              <p className="text-muted-foreground text-sm">
                {text(
                  "缺输出或技术错误不能通过；不确定必须升级处理。所有理由仅用于此任务，不进入聊天或知识库。",
                  "Missing output or technical errors cannot PASS; uncertainty requires escalation. Reasons stay in this task, outside chat and knowledge stores.",
                )}
              </p>
              <label className="block space-y-1 text-sm">
                <span>{text("独立复核理由", "Independent review reason")}</span>
                <Textarea
                  maxLength={2000}
                  value={note}
                  onChange={(e) => {
                    setNote(e.target.value);
                    revoke();
                  }}
                />
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                {text(
                  "我已核对当前证据并确认追加本轮独立决定，而不是正式批准。",
                  "I reviewed the current evidence and confirm appending this round's independent decision, not formal approval.",
                )}
              </label>
              <Button
                className="h-auto max-w-full text-left whitespace-normal"
                disabled={
                  !confirmed ||
                  !note.trim() ||
                  (decision === "pass" && !taskCanPass(opened))
                }
                onClick={() => void operate(submit, true)}
              >
                {text("追加独立决定", "Append independent decision")}
              </Button>
            </fieldset>
          </div>
        )}
        {result && (
          <section
            className="space-y-3"
            aria-label={text(
              "已验证历史逐条结论",
              "Verified historical case resolution",
            )}
          >
            <h4>
              {text("轮次", "Round")} {result.round} ·{" "}
              {labels[result.resolution.outcome]} · {result.resolution.basis}
            </h4>
            <p className="text-sm">
              {text(
                "仅为逐条结论，未接入运行汇总、报告或正式批准；历史轮次保持不变。",
                "Case resolution only; not integrated into run summaries, reports or formal approval. Historical rounds remain unchanged.",
              )}
            </p>
            {result.decisions.map((d) => (
              <div key={d.role} className="rounded border p-3 text-sm">
                <p>
                  {d.role} · {labels[d.decision]}
                </p>
                <pre
                  tabIndex={0}
                  className="max-h-64 overflow-auto break-words whitespace-pre-wrap"
                >
                  {d.note}
                </pre>
              </div>
            ))}
          </section>
        )}
      </fieldset>
    </section>
  );
}
