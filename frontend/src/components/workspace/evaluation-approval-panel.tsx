"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  approvalApi,
  type ApprovalAuditEvent,
  type ApprovalDecision,
  type ApprovalPreflight,
  type ApprovalView,
  type ProjectApproval,
} from "@/core/evaluation/approval-api";

const hex = (value: string, length: number) =>
  new RegExp(`^[0-9a-f]{${length}}$`).test(value);
const accountId = (value: string) =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);

/** Explicit, metadata-only approval workspace; no evidence or auto reads. */
export function EvaluationApprovalPanel({
  projectId,
  zh,
  pendingApprovals,
}: {
  projectId: string;
  zh: boolean;
  pendingApprovals: Map<string, string>;
}) {
  const [projectRows, setProjectRows] = useState<ProjectApproval[] | null>(
    null,
  );
  const [runId, setRunId] = useState("");
  const [runRows, setRunRows] = useState<ApprovalView[] | null>(null);
  const [audit, setAudit] = useState<ApprovalAuditEvent[] | null>(null);
  const [assessmentId, setAssessmentId] = useState("");
  const [assessmentHash, setAssessmentHash] = useState("");
  const [approverId, setApproverId] = useState("");
  const [decision, setDecision] = useState<ApprovalDecision>("approved");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [preflight, setPreflight] = useState<ApprovalPreflight | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const lock = useRef(false);
  const epoch = useRef(0);
  const key = `${projectId}:${runId}`;
  const pendingId = pendingApprovals.get(key) ?? null;

  useEffect(() => {
    return () => {
      epoch.current += 1;
    };
  }, []);

  useEffect(() => {
    epoch.current += 1;
    setRunRows(null);
    setAudit(null);
    setPreflight(null);
    setConfirmed(false);
    setError("");
    setNotice("");
  }, [projectId, runId]);

  const validTarget = () =>
    hex(runId, 32) && hex(assessmentId, 32) && hex(assessmentHash, 64);
  const validApprover = () => accountId(approverId);

  async function loadProject() {
    const at = ++epoch.current;
    setBusy(true);
    setError("");
    try {
      const rows = await approvalApi.projectApprovals(projectId);
      if (at === epoch.current) setProjectRows(rows);
    } catch {
      if (at === epoch.current)
        setError(
          zh
            ? "加载失败；检查权限、持久化和网络后重试。"
            : "Load failed; check permissions, persistence and network.",
        );
    } finally {
      if (at === epoch.current) setBusy(false);
    }
  }

  async function loadRun() {
    if (!hex(runId, 32)) {
      setError(
        zh ? "运行 ID 必须是 32 位十六进制。" : "Run ID must be 32 hex.",
      );
      return;
    }
    const at = ++epoch.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const [rows, events] = await Promise.all([
        approvalApi.runApprovals(projectId, runId),
        approvalApi.runAudit(projectId, runId),
      ]);
      if (at === epoch.current) {
        setRunRows(rows);
        setAudit(events);
      }
    } catch {
      if (at === epoch.current)
        setError(
          zh
            ? "加载失败；未知写入只按原 ID 对账，不自动重试。"
            : "Load failed; reconcile unknown writes by original ID only; never retry automatically.",
        );
    } finally {
      if (at === epoch.current) setBusy(false);
    }
  }

  async function checkPreflight() {
    if (!validTarget() || !validApprover()) {
      setError(
        zh
          ? "需要 32 位运行/评估 ID、64 位评估 hash 和规范账号 UUID。"
          : "Requires 32-hex run/assessment IDs, a 64-hex assessment hash and a canonical account UUID.",
      );
      return;
    }
    const at = ++epoch.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await approvalApi.preflight(
        projectId,
        runId,
        assessmentId,
        approverId,
      );
      if (at === epoch.current) setPreflight(result);
    } catch {
      if (at === epoch.current)
        setError(
          zh
            ? "预检失败；未写入任何批准或审计。"
            : "Preflight failed; no approval or audit was written.",
        );
    } finally {
      if (at === epoch.current) setBusy(false);
    }
  }

  async function record() {
    if (!validTarget() || !validApprover() || !confirmed || lock.current)
      return;
    if (decision === "revoked" && !note.trim()) {
      setError(zh ? "撤销必须提供理由。" : "A revocation reason is required.");
      return;
    }
    lock.current = true;
    const at = ++epoch.current;
    setBusy(true);
    setError("");
    setNotice("");
    const id =
      pendingApprovals.get(key) ?? crypto.randomUUID().replaceAll("-", "");
    pendingApprovals.set(key, id);
    setConfirmed(false);
    try {
      const result = await approvalApi.create(projectId, runId, id, {
        assessment_id: assessmentId,
        assessment_hash: assessmentHash,
        expected_previous_revision: runRows?.length ?? 0,
        approver_id: approverId,
        decision,
        ...(note.trim() ? { note: note.trim() } : {}),
        confirmed: true,
      });
      pendingApprovals.delete(key);
      if (at === epoch.current) {
        setRunRows((rows) => [result, ...(rows ?? [])]);
        setNotice(
          zh
            ? `已记录 revision ${result.revision}（${result.decision}）。`
            : `Recorded revision ${result.revision} (${result.decision}).`,
        );
      }
    } catch {
      try {
        const rows = await approvalApi.runApprovals(projectId, runId);
        if (rows.some((row) => row.id === id)) {
          pendingApprovals.delete(key);
          if (at === epoch.current) setRunRows(rows);
        }
      } catch {
        // Unknown result stays pending for same-ID read-only reconciliation.
      }
      if (at === epoch.current)
        setError(
          zh
            ? "写入结果未知；保留原 ID，只读对账后再决定，不自动重试或换 ID。"
            : "Write result unknown; keep the original ID, reconcile read-only, and never retry or replace the ID.",
        );
    } finally {
      lock.current = false;
      if (at === epoch.current) setBusy(false);
    }
  }

  const title = zh ? "正式批准" : "Formal approvals";
  const explanation = zh
    ? "只读元数据与显式人类决定；批准人不得是 owner 或该 run 的盲审/仲裁人。"
    : "Metadata-only reads and an explicit human decision; the approver must not be the owner or a blind reviewer/arbitrator of this run.";

  return (
    <section className="space-y-4 rounded-lg border p-4">
      <div>
        <h3 className="font-medium">{title}</h3>
        <p className="text-muted-foreground text-sm">{explanation}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          disabled={busy}
          onClick={() => void loadProject()}
        >
          {zh ? "加载项目批准" : "Load project approvals"}
        </Button>
        <Input
          aria-label={zh ? "运行 ID" : "Run ID"}
          value={runId}
          onChange={(event) => setRunId(event.target.value.trim())}
          placeholder={zh ? "运行 ID（32 hex）" : "Run ID (32 hex)"}
          className="max-w-sm"
        />
        <Button type="button" disabled={busy} onClick={() => void loadRun()}>
          {zh ? "加载运行批准与审计" : "Load run approvals and audit"}
        </Button>
      </div>
      {projectRows ? (
        <ul className="space-y-1 text-sm">
          {projectRows.length === 0 ? (
            <li className="text-muted-foreground">
              {zh
                ? "此项目暂无批准记录。"
                : "No approvals in this project yet."}
            </li>
          ) : (
            projectRows.map((row) => (
              <li key={row.id}>
                <span className="font-mono">{row.run_id}</span>
                {` · revision ${row.revision} · ${row.decision}`}
              </li>
            ))
          )}
        </ul>
      ) : null}
      {runRows ? (
        <div
          className="space-y-1 text-sm"
          aria-label={zh ? "运行批准" : "Run approvals"}
        >
          {runRows.length === 0 ? (
            <p className="text-muted-foreground">
              {zh ? "此运行暂无批准记录。" : "No approvals for this run yet."}
            </p>
          ) : (
            runRows.map((row) => (
              <p key={row.id}>
                {`revision ${row.revision} · ${row.decision} · ${row.approver_id}`}
              </p>
            ))
          )}
        </div>
      ) : null}
      {audit ? (
        <div
          className="space-y-1 text-sm"
          aria-label={zh ? "批准审计" : "Approval audit"}
        >
          {audit.map((event) => (
            <p key={`${event.run_id}:${event.sequence}`}>
              {`#${event.sequence} · ${event.action} · revision ${event.revision}`}
            </p>
          ))}
        </div>
      ) : null}
      {pendingId ? (
        <p className="text-sm text-amber-600" role="status">
          {zh
            ? "未知写入待对账，原 ID："
            : "Unknown write pending reconciliation, ID: "}
          <span className="font-mono">{pendingId}</span>
        </p>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-3">
        <Input
          aria-label={zh ? "评估 ID" : "Assessment ID"}
          value={assessmentId}
          onChange={(event) => setAssessmentId(event.target.value.trim())}
          placeholder={zh ? "评估 ID（32 hex）" : "Assessment ID (32 hex)"}
        />
        <Input
          aria-label={zh ? "评估 hash" : "Assessment hash"}
          value={assessmentHash}
          onChange={(event) => setAssessmentHash(event.target.value.trim())}
          placeholder={zh ? "评估 hash（64 hex）" : "Assessment hash (64 hex)"}
        />
        <Input
          aria-label={zh ? "审批人账号" : "Approver account"}
          value={approverId}
          onChange={(event) => setApproverId(event.target.value.trim())}
          placeholder={zh ? "审批人账号 UUID" : "Approver account UUID"}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          disabled={busy}
          onClick={() => void checkPreflight()}
        >
          {zh ? "检查批准资格" : "Check approval eligibility"}
        </Button>
        {preflight ? (
          <span className="text-sm" role="status">
            {preflight.eligible
              ? zh
                ? "可批准（仍需显式确认）"
                : "Eligible (explicit confirmation still required)"
              : `${zh ? "不可批准：" : "Blocked: "}${preflight.blockers.join(", ")}`}
            {preflight.latest_approval
              ? ` · latest revision ${preflight.latest_approval.revision} (${preflight.latest_approval.decision})`
              : ` · ${zh ? "暂无批准" : "no approval yet"}`}
          </span>
        ) : null}
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <select
          aria-label={zh ? "决定" : "Decision"}
          className="bg-background rounded-md border px-3 py-2 text-sm"
          value={decision}
          onChange={(event) => {
            setDecision(event.target.value as ApprovalDecision);
            setConfirmed(false);
          }}
        >
          <option value="approved">{zh ? "批准" : "Approved"}</option>
          <option value="revoked">{zh ? "撤销" : "Revoked"}</option>
        </select>
        <Textarea
          aria-label={zh ? "备注/撤销理由" : "Note / revocation reason"}
          value={note}
          onChange={(event) => {
            setNote(event.target.value);
            setConfirmed(false);
          }}
          placeholder={zh ? "可选；撤销必填" : "Optional; required to revoke"}
        />
      </div>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>
          {zh
            ? "我确认这是具名人类的显式决定；case PASS 或阈值达标不会自动产生批准。"
            : "I confirm this is an explicit named-human decision; case PASS or a met threshold never creates approval."}
        </span>
      </label>
      <Button
        type="button"
        disabled={busy || !confirmed || !validTarget() || !validApprover()}
        onClick={() => void record()}
      >
        {zh ? "记录批准/撤销" : "Record approval / revocation"}
      </Button>
      {error ? (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? <p className="text-sm text-emerald-600">{notice}</p> : null}
    </section>
  );
}
