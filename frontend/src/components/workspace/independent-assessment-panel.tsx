"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EvaluationCriteriaView } from "@/components/workspace/evaluation-criteria-view";
import { evaluationApi } from "@/core/evaluation/api";
import {
  assessmentIdValid,
  assessmentKey,
  parseAssessmentArchive,
  parseAssessmentHistory,
  parseAssessmentReceipt,
  parseIndependentAssessment,
  type AssessmentArchive,
  type AssessmentMetadata,
  type IndependentAssessment,
  type PendingAssessment,
  type PendingAssessments,
} from "@/core/evaluation/assessment-policy";

const selectClass =
  "bg-background w-full min-w-0 rounded-md border px-3 py-2 text-sm";
const runsSchema = z.object({
  runs: z
    .array(
      z.object({
        id: z.string().min(1).max(160),
        component_name: z.string().min(1).max(1_000),
        plan_label: z.string().min(1).max(160),
      }),
    )
    .max(200),
});

/** Key scope changes internally too; callers must keep the pending map in page memory. */
export function IndependentAssessmentPanel({
  projectId,
  zh,
  pendingAssessments,
}: {
  projectId: string;
  zh: boolean;
  pendingAssessments: PendingAssessments;
}) {
  return (
    <ProjectAssessmentWorkspace
      key={JSON.stringify([projectId, zh])}
      projectId={projectId}
      zh={zh}
      pendingAssessments={pendingAssessments}
    />
  );
}

function ProjectAssessmentWorkspace({
  projectId,
  zh,
  pendingAssessments,
}: {
  projectId: string;
  zh: boolean;
  pendingAssessments: PendingAssessments;
}) {
  const [runs, setRuns] = useState<z.infer<typeof runsSchema>["runs"]>([]);
  const [runId, setRunId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const lock = useRef(false);
  const epoch = useRef(0);
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  const pendingRunIds = [
    ...new Set(
      [...pendingAssessments.values()]
        .filter((p) => p.projectId === projectId)
        .map((p) => p.runId),
    ),
  ].filter((id) => !runs.some((r) => r.id === id));
  async function loadRuns() {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError(false);
    setRunId("");
    setRuns([]);
    try {
      const result = runsSchema.parse(
        await evaluationApi<unknown>(
          "evaluation/projects/" +
            encodeURIComponent(projectId) +
            "/review-runs",
        ),
      );
      if (new Set(result.runs.map((r) => r.id)).size !== result.runs.length)
        throw new Error("Duplicate run");
      if (token === epoch.current) setRuns(result.runs);
    } catch {
      if (token === epoch.current) setError(true);
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  return (
    <section
      aria-label={
        zh ? "独立全样本评估与修订" : "Independent all-sample assessments"
      }
      className="min-w-0 space-y-4 rounded-xl border p-4 md:p-5"
    >
      <h2 className="text-lg font-semibold">
        {zh
          ? "独立复核 → 全样本评估与不可变修订"
          : "Independent review → all-sample assessment revisions"}
      </h2>
      <p className="text-muted-foreground text-sm">
        {zh
          ? "只读取本人项目的独立双盲 / 仲裁证据；不是上方 owner 自复核汇总。全部冻结效果样本参与分母，缺证据不剔除。仅采集后的评估，不补做预运行审批、不启动评测或模型调用，也不接入旧报告 / 复测。"
          : "Owner-only independent blind-review / arbitration evidence, separate from the owner self-review summary above. ALL frozen effectiveness samples remain in the denominator. Post-collection assessment only: no retroactive pre-run approval, execution, model calls or legacy report / retest changes."}
      </p>
      <p className="text-muted-foreground text-xs">
        {zh
          ? "待核对 ID 仅保存在本页内存，跨项目切换保留；刷新或离开整页前请自行记录 ID。不会自动轮询、重试或写入浏览器持久缓存。"
          : "Pending IDs stay in page memory across project switches. Record IDs before reloading or leaving this page. No automatic polling, retry or persistent browser cache."}
      </p>
      <div className="flex min-w-0 flex-wrap items-end gap-3">
        <Button
          type="button"
          variant="outline"
          className="h-auto whitespace-normal"
          disabled={busy}
          onClick={() => void loadRuns()}
        >
          {zh ? "加载 / 刷新评估运行列表" : "Load / refresh assessment runs"}
        </Button>
        <label className="min-w-0 flex-1 space-y-1 text-sm">
          <span>{zh ? "独立评估运行" : "Independent assessment run"}</span>
          <select
            className={selectClass}
            value={runId}
            disabled={busy}
            onChange={(e) => setRunId(e.target.value)}
          >
            <option value="">{zh ? "请选择运行" : "Choose a run"}</option>
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {run.component_name} · {run.plan_label} · {run.id}
              </option>
            ))}
            {pendingRunIds.map((id) => (
              <option key={id} value={id}>
                {zh ? "待核对回执运行" : "Pending receipt run"}: {id}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {zh
            ? "无法读取运行列表，请核对权限后手动刷新。"
            : "Cannot read runs; check permissions before manually refreshing."}
        </p>
      )}
      {runId && (
        <RunAssessmentWorkspace
          key={runId}
          projectId={projectId}
          runId={runId}
          pendingAssessments={pendingAssessments}
          zh={zh}
        />
      )}
    </section>
  );
}

function RunAssessmentWorkspace({
  projectId,
  runId,
  pendingAssessments,
  zh,
}: {
  projectId: string;
  runId: string;
  pendingAssessments: PendingAssessments;
  zh: boolean;
}) {
  const key = assessmentKey(projectId, runId);
  const [preview, setPreview] = useState<IndependentAssessment | null>(null);
  const [history, setHistory] = useState<AssessmentMetadata[] | null>(null);
  const [opened, setOpened] = useState<AssessmentArchive | null>(null);
  const [pending, setPending] = useState<PendingAssessment | null>(
    () => pendingAssessments.get(key) ?? null,
  );
  const [lookupId, setLookupId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [notice, setNotice] = useState(false);
  const lock = useRef(false);
  const epoch = useRef(0);
  const base =
    "evaluation/projects/" +
    encodeURIComponent(projectId) +
    "/review-runs/" +
    encodeURIComponent(runId);
  const previousRevision = history?.[0]?.revision ?? 0;
  const unknownWrite = !!pending && !pending.receipt;
  const canArchive =
    !!preview &&
    history !== null &&
    previousRevision < 1_000 &&
    !pending &&
    !busy;
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  async function operate(action: (current: () => boolean) => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError(false);
    setNotice(false);
    setConfirmed(false);
    try {
      await action(() => token === epoch.current);
    } catch {
      if (token === epoch.current) setError(true);
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  function rememberReceipt(
    attempt: PendingAssessment,
    receipt: AssessmentArchive,
    current: () => boolean,
  ) {
    const updated = { ...attempt, receipt };
    // A late known success belongs to its original scope, never the newly selected project/run.
    if (pendingAssessments.get(key)?.id === attempt.id)
      pendingAssessments.set(key, updated);
    if (current()) {
      setPending(updated);
      setOpened(receipt);
      setNotice(true);
    }
  }
  async function load(current: () => boolean) {
    setPreview(null);
    setHistory(null);
    setOpened(null);
    const [rawPreview, rawHistory] = await Promise.all([
      evaluationApi<unknown>(base + "/independent-assessment"),
      evaluationApi<unknown>(base + "/assessments"),
    ]);
    const nextPreview = parseIndependentAssessment(
      rawPreview,
      projectId,
      runId,
    );
    const nextHistory = parseAssessmentHistory(rawHistory, projectId, runId);
    if (!current()) return;
    setPreview(nextPreview);
    setHistory(nextHistory);
    // Only a verified receipt plus an explicit fresh read allows starting another revision.
    const remembered = pendingAssessments.get(key);
    if (remembered?.receipt) {
      pendingAssessments.delete(key);
      setPending(null);
    }
  }
  async function create(current: () => boolean) {
    if (!canArchive || !confirmed || !preview || history === null) return;
    const existing = pendingAssessments.get(key);
    if (existing) {
      setPending(existing);
      return;
    }
    const id = crypto.randomUUID().replaceAll("-", "");
    if (!assessmentIdValid(id)) throw new Error("Invalid revision ID");
    const attempt: PendingAssessment = {
      id,
      projectId,
      runId,
      payload: {
        summary_hash: preview.summary_hash,
        expected_previous_revision: previousRevision,
        confirmed: true,
      },
    };
    // Store synchronously BEFORE sending. Any error remains unknown, including 404 reconciliation.
    pendingAssessments.set(key, attempt);
    setPending(attempt);
    setPreview(null);
    setOpened(null);
    const raw = await evaluationApi<unknown>(
      base + "/assessments/" + id,
      attempt.payload,
    );
    rememberReceipt(attempt, parseAssessmentReceipt(raw, attempt), current);
  }
  async function reconcile(current: () => boolean) {
    if (!pending) return;
    setOpened(null);
    const raw = await evaluationApi<unknown>(
      base + "/assessments/" + pending.id,
    );
    rememberReceipt(pending, parseAssessmentReceipt(raw, pending), current);
  }
  async function openArchive(
    current: () => boolean,
    id: string,
    metadata?: AssessmentMetadata,
  ) {
    setOpened(null);
    const raw = await evaluationApi<unknown>(base + "/assessments/" + id);
    const archive = parseAssessmentArchive(raw, projectId, runId, id);
    if (
      metadata &&
      (archive.revision !== metadata.revision ||
        archive.assessment_hash !== metadata.assessment_hash ||
        archive.assessment.summary_hash !== metadata.summary_hash ||
        archive.created_at_ms !== metadata.created_at_ms)
    )
      throw new Error("Archive metadata mismatch");
    if (current()) setOpened(archive);
  }
  return (
    <div className="min-w-0 space-y-4 border-t pt-4">
      <p className="text-xs break-all">
        {zh ? "运行" : "Run"}: {runId}
      </p>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {zh
            ? "操作未确认成功。请核对权限、计划类型、密钥或并发变化后手动读取；不显示原始错误，不自动重发。未知写入只能按相同 ID GET 核对，404 也不能证明稍后的写入不会成功。"
            : "Operation not confirmed. Check permissions, plan mode, key or concurrent changes before an explicit read. No raw errors or automatic resend. Unknown writes require same-ID GET reconciliation; even 404 does not prove a delayed write cannot succeed."}
        </p>
      )}
      {notice && (
        <p role="status" className="text-sm">
          {zh
            ? "评估修订回执已确认；不是正式批准。下一次归档前请明确刷新预览和历史。"
            : "Assessment revision receipt confirmed; not approval. Explicitly refresh preview and history before another archive."}
        </p>
      )}
      {pending && (
        <div
          aria-label={zh ? "评估待核对回执" : "Pending assessment receipt"}
          className="min-w-0 space-y-2 rounded-md border p-3 text-sm"
        >
          <p className="break-all">
            {zh ? "评估 ID" : "Assessment ID"}: {pending.id}
          </p>
          <p>
            {zh ? "预期修订" : "Expected revision"}:{" "}
            {pending.payload.expected_previous_revision + 1} ·{" "}
            {pending.receipt
              ? zh
                ? "回执已确认"
                : "Receipt confirmed"
              : zh
                ? "写入结果未知；不会生成新 ID 或重发"
                : "Write result unknown; no new ID or resend"}
          </p>
          <Button
            type="button"
            variant="outline"
            className="h-auto whitespace-normal"
            disabled={busy}
            onClick={() => void operate(reconcile)}
          >
            {zh
              ? "按相同评估 ID 核对（GET）"
              : "Reconcile same assessment ID (GET)"}
          </Button>
        </div>
      )}
      <Button
        type="button"
        variant="outline"
        className="h-auto whitespace-normal"
        disabled={busy || unknownWrite}
        onClick={() => void operate(load)}
      >
        {zh
          ? "加载 / 刷新独立预览与修订历史"
          : "Load / refresh independent preview and revisions"}
      </Button>
      {preview && (
        <section
          aria-label={
            zh ? "当前独立评估预览" : "Current independent assessment preview"
          }
          className="min-w-0 space-y-3"
        >
          <h3 className="font-semibold">
            {zh ? "当前预览（尚未归档）" : "Current preview (not archived)"}
          </h3>
          <AssessmentView assessment={preview} zh={zh} />
        </section>
      )}
      <fieldset
        disabled={!canArchive}
        className="min-w-0 space-y-3 rounded-md border p-3"
      >
        <legend className="text-sm font-semibold">
          {zh
            ? "明确追加不可变评估修订"
            : "Explicitly append an immutable assessment revision"}
        </legend>
        <p className="text-muted-foreground text-xs">
          {zh
            ? "允许保存尚不完整的 provisional 评估，但不会批准、补充证据或替换既有报告。归档绑定当前看到的汇总 hash 和上一个修订；并发变更会拒绝。"
            : "Provisional assessments may be archived, but this does not approve, add evidence or replace reports. The archive binds the viewed summary hash and previous revision; concurrent changes are rejected."}
        </p>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1 shrink-0"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            {zh
              ? "我已查看独立全样本评估并明确确认追加修订；理解未完成 / 达标都不代表正式批准。"
              : "I viewed the independent all-sample assessment and explicitly confirm appending a revision; incomplete or threshold met is not formal approval."}
          </span>
        </label>
        <p className="text-xs">
          {zh ? "上一个修订 / 下一修订" : "Previous / next revision"}:{" "}
          {history === null
            ? "—"
            : previousRevision +
              " / " +
              (previousRevision < 1_000
                ? previousRevision + 1
                : zh
                  ? "已达上限"
                  : "limit reached")}
        </p>
        <Button
          type="button"
          className="h-auto whitespace-normal"
          disabled={!canArchive || !confirmed}
          onClick={() => void operate(create)}
        >
          {zh
            ? "确认归档独立评估修订"
            : "Archive independent assessment revision"}
        </Button>
      </fieldset>
      <section
        aria-label={zh ? "不可变评估历史" : "Immutable assessment history"}
        className="min-w-0 space-y-3"
      >
        <h3 className="font-semibold">
          {zh ? "历史修订（最近 100 项）" : "Historical revisions (latest 100)"}
        </h3>
        <p className="text-muted-foreground text-xs">
          {zh
            ? "历史打开只读取固定归档，不读取当前预览、不重新计算当前意见；可按已有 ID 查找更早修订。"
            : "History opens the fixed archive only, without reading a current preview or recomputing current decisions. Use an existing ID to open older revisions."}
        </p>
        {history?.length === 0 && (
          <p className="text-sm">
            {zh ? "暂无已归档修订。" : "No archived revisions yet."}
          </p>
        )}
        <ul className="min-w-0 space-y-2">
          {history?.map((row) => (
            <li
              key={row.id}
              className="flex min-w-0 flex-wrap items-center gap-2 text-xs"
            >
              <span className="min-w-0 break-all">
                #{row.revision} · {row.id}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-auto whitespace-normal"
                disabled={busy}
                onClick={() =>
                  void operate((current) => openArchive(current, row.id, row))
                }
              >
                {zh ? "打开评估修订 " : "Open assessment revision "}
                {row.revision}
              </Button>
            </li>
          ))}
        </ul>
        <div className="flex min-w-0 flex-wrap items-end gap-2">
          <label className="min-w-0 flex-1 space-y-1 text-sm">
            <span>{zh ? "评估修订 ID" : "Assessment revision ID"}</span>
            <Input
              maxLength={32}
              value={lookupId}
              onChange={(e) => {
                setLookupId(e.target.value);
                setConfirmed(false);
              }}
              disabled={busy}
            />
          </label>
          <Button
            type="button"
            variant="outline"
            className="h-auto whitespace-normal"
            disabled={busy || !assessmentIdValid(lookupId)}
            onClick={() =>
              void operate((current) => openArchive(current, lookupId))
            }
          >
            {zh ? "按 ID 打开评估（GET）" : "Open assessment by ID (GET)"}
          </Button>
        </div>
      </section>
      {opened && (
        <section
          aria-label={
            zh
              ? "已打开的不可变评估修订"
              : "Opened immutable assessment revision"
          }
          className="min-w-0 space-y-3 rounded-lg border p-3"
        >
          <h3 className="font-semibold">
            {zh ? "已归档修订" : "Archived revision"} #{opened.revision} ·{" "}
            {zh ? "未批准" : "Not approved"}
          </h3>
          <p className="text-xs break-all">
            ID: {opened.id} · {zh ? "创建时间（毫秒）" : "Created (ms)"}:{" "}
            {opened.created_at_ms}
          </p>
          <p className="text-xs break-all">
            {zh ? "归档指纹" : "Archive fingerprint"}: {opened.assessment_hash}
          </p>
          <AssessmentView assessment={opened.assessment} zh={zh} />
        </section>
      )}
    </div>
  );
}

function AssessmentView({
  assessment,
  zh,
}: {
  assessment: IndependentAssessment;
  zh: boolean;
}) {
  const labels = {
    pass: zh ? "通过" : "Pass",
    fail: zh ? "不通过" : "Fail",
    uncertain: zh ? "待确认" : "Uncertain",
    unreviewed: zh ? "未复核" : "Unreviewed",
  };
  const blockers = {
    collection_not_finished: zh
      ? "采集尚未正常完成"
      : "Collection not finished",
    technical_incomplete: zh
      ? "缺少采集输出证据"
      : "Missing collected output evidence",
    independent_review_incomplete: zh
      ? "独立复核尚未完成"
      : "Independent review incomplete",
    uncertain: zh ? "存在待确认结论" : "Uncertain decisions remain",
    conflicting_independent_resolutions: zh
      ? "同一样本的独立任务结论冲突"
      : "Conflicting independent task resolutions",
  };
  return (
    <div className="min-w-0 space-y-3 text-sm break-words">
      <p>
        {assessment.component_name} · {assessment.plan_label}
      </p>
      <p className="text-xl font-semibold tabular-nums">
        {assessment.human_pass_rate.numerator} /{" "}
        {assessment.human_pass_rate.denominator} ·{" "}
        {(assessment.human_pass_rate.value * 100).toFixed(2)}%
      </p>
      <p>
        {assessment.readiness === "review_complete"
          ? zh
            ? "独立复核完成（未批准）"
            : "Independent review complete (not approved)"
          : zh
            ? "独立评估尚不完整（未批准）"
            : "Independent assessment incomplete (not approved)"}
      </p>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {(["pass", "fail", "uncertain", "unreviewed"] as const).map((kind) => (
          <div key={kind}>
            <dt>{labels[kind]}</dt>
            <dd>{assessment.counts[kind]}</dd>
          </div>
        ))}
      </dl>
      <p>
        {zh ? "已采集输出 / 其他" : "Collected output / other"}:{" "}
        {assessment.technical_counts.collected} /{" "}
        {assessment.technical_counts.other}
      </p>
      {assessment.blockers.length > 0 && (
        <ul className="list-inside list-disc">
          {assessment.blockers.map((key) => (
            <li key={key}>{blockers[key]}</li>
          ))}
        </ul>
      )}
      <EvaluationCriteriaView
        assessment={assessment.criteria_evaluation}
        zh={zh}
      />
      <p className="text-xs break-all">
        {zh ? "汇总指纹" : "Summary fingerprint"}: {assessment.summary_hash}
      </p>
      <p className="text-muted-foreground text-xs">
        {zh
          ? "指纹用于完整性绑定，不是独立签名。采集后评估不追认预运行审批；不展示 Q/A、参考答案、复核理由或人员身份。"
          : "Fingerprints bind integrity; they are not independent signatures. Post-collection assessment is not retroactive pre-run approval. No Q/A, reference answers, review reasons or reviewer identities are shown."}
      </p>
      <details className="min-w-0 rounded-md border p-3">
        <summary className="cursor-pointer">
          {zh ? "全部冻结样本的绑定记录" : "All frozen sample commitments"} (
          {assessment.cases.length})
        </summary>
        <div
          tabIndex={0}
          aria-label={zh ? "全样本绑定记录" : "All-sample commitments"}
          className="mt-3 max-h-72 min-w-0 space-y-3 overflow-auto text-xs"
        >
          {assessment.cases.map((item) => (
            <details
              key={item.ordinal}
              className="min-w-0 rounded-md border p-2"
            >
              <summary className="cursor-pointer break-words">
                #{item.ordinal} · {labels[item.outcome]} ·{" "}
                {zh ? "任务" : "Tasks"}: {item.tasks.length}
              </summary>
              <p className="break-all">
                {zh ? "样本指纹" : "Case fingerprint"}: {item.case_hash}
              </p>
              <ul className="space-y-2">
                {item.tasks.map((task) => (
                  <li key={task.task_id} className="break-all">
                    {task.task_id} ·{" "}
                    {zh
                      ? "轮次 / 任务修订 / 结论修订"
                      : "Round / task revision / resolution revision"}
                    : {task.round} / {task.task_revision} /{" "}
                    {task.resolution_revision} · {task.status}
                    <br />
                    {task.subject_hash}
                    <br />
                    {task.resolution_hash ?? "—"}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      </details>
    </div>
  );
}
