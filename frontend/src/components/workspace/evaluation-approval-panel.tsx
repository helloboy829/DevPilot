"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  approvalApi,
  type ApprovalAuditEvent,
  type ApprovalChainIntegrity,
  type ApprovalCapabilities,
  type ApprovalChainSummary,
  type ApprovalDecision,
  type ApprovalPreflight,
  type ApprovalSignoffProgress,
  type ApprovalView,
  type RunAssessment,
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
  const [integrity, setIntegrity] = useState<ApprovalChainIntegrity | null>(
    null,
  );
  const [projectIntegrity, setProjectIntegrity] =
    useState<ApprovalChainSummary | null>(null);
  const [signoff, setSignoff] = useState<ApprovalSignoffProgress | null>(null);
  const [assessments, setAssessments] = useState<RunAssessment[] | null>(null);
  const [requiredSignoff, setRequiredSignoff] = useState("");
  const [capabilities, setCapabilities] = useState<ApprovalCapabilities | null>(
    null,
  );
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
    setProjectRows(null);
    setCapabilities(null);
    setRunId("");
    setAssessmentId("");
    setAssessmentHash("");
    setApproverId("");
  }, [projectId]);

  useEffect(() => {
    epoch.current += 1;
    setRunRows(null);
    setAudit(null);
    setIntegrity(null);
    setProjectIntegrity(null);
    setSignoff(null);
    setAssessments(null);
    setRequiredSignoff("");
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
        setIntegrity(null);
        setProjectIntegrity(null);
        setSignoff(null);
        const pending = pendingApprovals.get(key);
        if (pending && rows.some((row) => row.id === pending)) {
          pendingApprovals.delete(key);
          setIntegrity(null);
          setProjectIntegrity(null);
          setSignoff(null);
          setNotice(
            zh
              ? "已按原 ID 完成只读对账；未重试或更换 ID。"
              : "Reconciled by original ID; nothing was retried or replaced.",
          );
        }
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

  async function loadCapabilities() {
    const at = ++epoch.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await approvalApi.capabilities(projectId);
      if (at === epoch.current) setCapabilities(result);
    } catch {
      if (at === epoch.current)
        setError(
          zh
            ? "批准能力诊断加载失败；未读取批准或证据。"
            : "Approval capability diagnostic failed; no approval or evidence was read.",
        );
    } finally {
      if (at === epoch.current) setBusy(false);
    }
  }

  async function loadAssessments() {
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
      const rows = await approvalApi.runAssessments(projectId, runId);
      if (at === epoch.current) setAssessments(rows);
    } catch {
      if (at === epoch.current)
        setError(
          zh
            ? "评估元数据加载失败；未读取评估文档。"
            : "Assessment metadata load failed; no assessment document was read.",
        );
    } finally {
      if (at === epoch.current) setBusy(false);
    }
  }

  async function checkProjectIntegrity() {
    const at = ++epoch.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await approvalApi.projectChainIntegrity(projectId);
      if (at === epoch.current) setProjectIntegrity(result);
    } catch {
      if (at === epoch.current)
        setError(
          zh
            ? "项目完整性检查失败；未读取或写入批准文档。"
            : "Project integrity check failed; no approval document was read or written.",
        );
    } finally {
      if (at === epoch.current) setBusy(false);
    }
  }

  async function checkIntegrity() {
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
      const result = await approvalApi.chainIntegrity(projectId, runId);
      if (at === epoch.current) setIntegrity(result);
    } catch {
      if (at === epoch.current)
        setError(
          zh
            ? "完整性检查失败；未读取或写入批准文档。"
            : "Integrity check failed; no approval document was read or written.",
        );
    } finally {
      if (at === epoch.current) setBusy(false);
    }
  }

  async function checkSignoff() {
    if (!hex(runId, 32)) {
      setError(
        zh ? "运行 ID 必须是 32 位十六进制。" : "Run ID must be 32 hex.",
      );
      return;
    }
    const proposed = requiredSignoff.trim();
    let required: number | undefined;
    if (proposed) {
      const value = Number(proposed);
      if (!Number.isInteger(value) || value < 1 || value > 10) {
        setError(
          zh
            ? "拟议所需审批人数必须在 1–10 之间。"
            : "Required approvers must be 1-10.",
        );
        return;
      }
      required = value;
    }
    const at = ++epoch.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result =
        required === undefined
          ? await approvalApi.signoffProgress(projectId, runId)
          : await approvalApi.signoffProgress(projectId, runId, required);
      if (at === epoch.current) setSignoff(result);
    } catch {
      if (at === epoch.current)
        setError(
          zh
            ? "签署进度检查失败；未读取或写入批准文档。"
            : "Sign-off progress check failed; no approval document was read or written.",
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
        setProjectRows((rows) => {
          if (!rows) return rows;
          const next = {
            run_id: runId,
            id: result.id,
            revision: result.revision,
            decision: result.decision,
            assessment_id: result.assessment.id,
            assessment_hash: result.assessment.assessment_hash,
            created_at_ms: result.created_at_ms,
          };
          return rows.some((row) => row.run_id === runId)
            ? rows.map((row) => (row.run_id === runId ? next : row))
            : [next, ...rows];
        });
        setIntegrity(null);
        setProjectIntegrity(null);
        setSignoff(null);
        setPreflight(null);
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
    <section aria-label={title} className="space-y-4 rounded-lg border p-4">
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
        <Button
          type="button"
          disabled={busy}
          onClick={() => void loadCapabilities()}
        >
          {zh ? "加载批准能力" : "Load approval capabilities"}
        </Button>
        <Button
          type="button"
          disabled={busy}
          onClick={() => void checkProjectIntegrity()}
        >
          {zh ? "检查项目批准链" : "Check project approval chains"}
        </Button>
        {projectRows && projectRows.length > 0 ? (
          <select
            aria-label={zh ? "批准运行" : "Approval run"}
            className="bg-background rounded-md border px-3 py-2 text-sm"
            value={projectRows.some((row) => row.run_id === runId) ? runId : ""}
            onChange={(event) => setRunId(event.target.value)}
          >
            <option value="">{zh ? "选择运行" : "Select run"}</option>
            {projectRows.map((row) => (
              <option key={row.run_id} value={row.run_id}>
                {`${row.run_id} · r${row.revision} ${row.decision}`}
              </option>
            ))}
          </select>
        ) : null}
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
        <Button
          type="button"
          disabled={busy}
          onClick={() => void loadAssessments()}
        >
          {zh ? "加载运行评估" : "Load run assessments"}
        </Button>
        <Button
          type="button"
          disabled={busy}
          onClick={() => void checkIntegrity()}
        >
          {zh ? "检查批准链完整性" : "Check approval chain integrity"}
        </Button>
        <Input
          aria-label={
            zh
              ? "拟议所需审批人数（仅咨询）"
              : "Proposed required approvers (advisory)"
          }
          type="number"
          min={1}
          max={10}
          value={requiredSignoff}
          onChange={(event) => {
            setRequiredSignoff(event.target.value);
            setSignoff(null);
            setError("");
          }}
          className="max-w-xs"
          placeholder={zh ? "可选：1–10" : "Optional: 1-10"}
        />
        <Button
          type="button"
          disabled={busy}
          onClick={() => void checkSignoff()}
        >
          {zh ? "检查签署进度" : "Check approver sign-off progress"}
        </Button>
      </div>
      {capabilities ? (
        <div className="space-y-1 text-sm" role="status">
          <p>
            {zh
              ? "批准能力：owner 代为记录；多级政策仅咨询；审批人登录、强制签核、通知与导出未实现。"
              : "Approval capabilities: owner records on behalf; multi-level policy is advisory only; approver login, enforcement, notifications and export are not implemented."}
          </p>
          <p>{`${zh ? "批准：" : "Approval: "}${zh ? "未授权" : "not authorized"}`}</p>
          <ul className="list-disc pl-5 font-mono">
            {capabilities.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      ) : null}
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
      {projectIntegrity ? (
        <p className="text-sm" role="status">
          {projectIntegrity.status === "verified"
            ? zh
              ? `项目批准链已校验：${projectIntegrity.verified_runs}/${projectIntegrity.runs} 个运行 · ${projectIntegrity.approvals} 条批准 / ${projectIntegrity.events} 条事件`
              : `Project chains verified: ${projectIntegrity.verified_runs} of ${projectIntegrity.runs} runs · ${projectIntegrity.approvals} approvals / ${projectIntegrity.events} events`
            : projectIntegrity.status === "broken"
              ? zh
                ? `项目批准链损坏：${projectIntegrity.broken_runs}/${projectIntegrity.runs} 个运行 · ${projectIntegrity.blockers.join(", ")}`
                : `Project chains broken: ${projectIntegrity.broken_runs} of ${projectIntegrity.runs} runs · ${projectIntegrity.blockers.join(", ")}`
              : zh
                ? `项目批准链无法校验：${projectIntegrity.blockers.join(", ") || "unspecified"}`
                : `Project chains unverifiable: ${projectIntegrity.blockers.join(", ") || "unspecified"}`}
        </p>
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
      {integrity ? (
        <p className="text-sm" role="status">
          {integrity.status === "verified"
            ? `Chain verified: ${integrity.approvals} approvals / ${integrity.events} events`
            : `Chain broken: ${integrity.blockers.join(", ") || "unspecified"}`}
        </p>
      ) : null}
      {signoff ? (
        <div className="space-y-1 text-sm" role="status">
          <p>{`Sign-off progress: ${signoff.revisions} revisions · ${signoff.distinct_approvers} distinct approvers · latest ${signoff.latest_decision ?? "none"}`}</p>
          <p>
            {zh
              ? "签核政策未定义；所需不同审批人数：n/a"
              : "Policy not defined; required distinct approvers: n/a"}
          </p>
          <ul className="list-disc pl-5 font-mono">
            {signoff.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
          {signoff.stored_policy ? (
            <p>
              {`Stored advisory policy revision ${signoff.stored_policy.revision}: ${signoff.stored_policy.required_distinct_approvers} approvers`}
            </p>
          ) : null}
          {signoff.requirement ? (
            <div className="space-y-1 border-t pt-2">
              <p>
                {`Advisory requirement${
                  signoff.requirement.source === "stored_advisory"
                    ? " (stored policy)"
                    : ""
                }: ${
                  signoff.requirement.satisfied ? "satisfied" : "not satisfied"
                }${
                  signoff.requirement.blockers.length
                    ? ` · ${signoff.requirement.blockers.join(", ")}`
                    : ""
                }`}
              </p>
              <p className="text-muted-foreground">
                {zh
                  ? "仅咨询：不强制任何签核政策。"
                  : signoff.stored_policy
                    ? "Advisory only; the stored policy is not enforced."
                    : "Advisory only; no policy is stored or enforced."}
              </p>
            </div>
          ) : null}
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
      {assessments ? (
        assessments.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {zh ? "此运行暂无评估修订。" : "No assessments for this run yet."}
          </p>
        ) : (
          <select
            aria-label={zh ? "评估修订" : "Assessment revision"}
            className="bg-background max-w-md rounded-md border px-3 py-2 text-sm"
            value=""
            onChange={(event) => {
              const row = assessments.find(
                (item) => item.id === event.target.value,
              );
              if (!row) return;
              setAssessmentId(row.id);
              setAssessmentHash(row.assessment_hash);
              setPreflight(null);
              setConfirmed(false);
              setError("");
              setNotice("");
            }}
          >
            <option value="">
              {zh ? "选择评估修订" : "Select assessment revision"}
            </option>
            {assessments.map((row) => (
              <option key={row.id} value={row.id}>
                {`r${row.revision} · ${row.id}`}
              </option>
            ))}
          </select>
        )
      ) : null}
      <div className="grid gap-2 sm:grid-cols-3">
        <Input
          aria-label={zh ? "评估 ID" : "Assessment ID"}
          value={assessmentId}
          onChange={(event) => {
            setAssessmentId(event.target.value.trim());
            setPreflight(null);
            setConfirmed(false);
            setError("");
            setNotice("");
          }}
          placeholder={zh ? "评估 ID（32 hex）" : "Assessment ID (32 hex)"}
        />
        <Input
          aria-label={zh ? "评估 hash" : "Assessment hash"}
          value={assessmentHash}
          onChange={(event) => {
            setAssessmentHash(event.target.value.trim());
            setPreflight(null);
            setConfirmed(false);
            setError("");
            setNotice("");
          }}
          placeholder={zh ? "评估 hash（64 hex）" : "Assessment hash (64 hex)"}
        />
        <Input
          aria-label={zh ? "审批人账号" : "Approver account"}
          value={approverId}
          onChange={(event) => {
            setApproverId(event.target.value.trim());
            setPreflight(null);
            setConfirmed(false);
            setError("");
            setNotice("");
          }}
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
