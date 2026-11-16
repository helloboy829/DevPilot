"use client";

import { useEffect, useRef, useState } from "react";

import {
  approvalApi,
  type ApprovalAuditEvent,
  type ApprovalChainIntegrity,
  type ApprovalCapabilities,
  type ApprovalChainSummary,
  type ApprovalDecision,
  type ApprovalPreflight,
  type ApprovalSignoffProgress,
  type ApprovalMetadata,
  type RunAssessment,
  type ProjectApproval,
} from "@/core/evaluation/approval-api";

const hex = (value: string, length: number) =>
  new RegExp(`^[0-9a-f]{${length}}$`).test(value);
const accountId = (value: string) =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);

/** Owns request scopes and unknown writes; the view never schedules effects. */
export function useApprovalWorkspace(
  projectId: string,
  zh: boolean,
  pendingApprovals: Map<string, string>,
) {
  const [projectRows, setProjectRows] = useState<ProjectApproval[] | null>(
    null,
  );
  const [runId, setRunId] = useState("");
  const [runRows, setRunRows] = useState<ApprovalMetadata[] | null>(null);
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
    setBusy(false);
    setRunRows(null);
    setNote("");
    setDecision("approved");
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

  function invalidate() {
    epoch.current += 1;
    setBusy(false);
  }

  function begin() {
    const token = ++epoch.current;
    setBusy(true);
    setError("");
    setNotice("");
    return token;
  }

  function finish(token: number) {
    if (token === epoch.current) setBusy(false);
  }

  async function read<T>(
    request: () => Promise<T>,
    accept: (result: T) => void,
    message: string,
  ) {
    const at = begin();
    try {
      const result = await request();
      if (at === epoch.current) accept(result);
    } catch {
      if (at === epoch.current) setError(message);
    } finally {
      finish(at);
    }
  }

  function edit<T>(setter: (value: T) => void) {
    return (value: T) => {
      invalidate();
      setter(value);
      setPreflight(null);
      setConfirmed(false);
    };
  }

  function editRequiredSignoff(value: string) {
    invalidate();
    setRequiredSignoff(value);
    setSignoff(null);
  }

  const validTarget = () =>
    hex(runId, 32) && hex(assessmentId, 32) && hex(assessmentHash, 64);
  const validApprover = () => accountId(approverId);

  async function loadProject() {
    await read(
      () => approvalApi.projectApprovals(projectId),
      (rows) => setProjectRows(rows),
      zh
        ? "加载失败；检查权限、持久化和网络后重试。"
        : "Load failed; check permissions, persistence and network.",
    );
  }

  async function loadRun() {
    if (!hex(runId, 32)) {
      setError(
        zh ? "运行 ID 必须是 32 位十六进制。" : "Run ID must be 32 hex.",
      );
      return;
    }
    const at = begin();
    try {
      const pending = pendingApprovals.get(key);
      const [rows, events, receipt] = await Promise.all([
        approvalApi.runApprovals(projectId, runId),
        approvalApi.runAudit(projectId, runId),
        pending
          ? approvalApi
              .approvalMetadata(projectId, runId, pending)
              .catch(() => null)
          : null,
      ]);
      if (pending && receipt?.id === pending) pendingApprovals.delete(key);
      if (at === epoch.current) {
        setRunRows(rows);
        setAudit(events);
        setIntegrity(null);
        setProjectIntegrity(null);
        setSignoff(null);
        if (pending && receipt?.id === pending) {
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
      finish(at);
    }
  }

  async function loadCapabilities() {
    await read(
      () => approvalApi.capabilities(projectId),
      (result) => setCapabilities(result),
      zh
        ? "批准能力诊断加载失败；未读取批准或证据。"
        : "Approval capability diagnostic failed; no approval or evidence was read.",
    );
  }

  async function loadAssessments() {
    if (!hex(runId, 32)) {
      setError(
        zh ? "运行 ID 必须是 32 位十六进制。" : "Run ID must be 32 hex.",
      );
      return;
    }
    await read(
      () => approvalApi.runAssessments(projectId, runId),
      (rows) => setAssessments(rows),
      zh
        ? "评估元数据加载失败；未读取评估文档。"
        : "Assessment metadata load failed; no assessment document was read.",
    );
  }

  async function checkProjectIntegrity() {
    await read(
      () => approvalApi.projectChainIntegrity(projectId),
      (result) => setProjectIntegrity(result),
      zh
        ? "项目完整性检查失败；未读取或写入批准文档。"
        : "Project integrity check failed; no approval document was read or written.",
    );
  }

  async function checkIntegrity() {
    if (!hex(runId, 32)) {
      setError(
        zh ? "运行 ID 必须是 32 位十六进制。" : "Run ID must be 32 hex.",
      );
      return;
    }
    await read(
      () => approvalApi.chainIntegrity(projectId, runId),
      (result) => setIntegrity(result),
      zh
        ? "完整性检查失败；未读取或写入批准文档。"
        : "Integrity check failed; no approval document was read or written.",
    );
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
    await read(
      () =>
        required === undefined
          ? approvalApi.signoffProgress(projectId, runId)
          : approvalApi.signoffProgress(projectId, runId, required),
      (result) => setSignoff(result),
      zh
        ? "签署进度检查失败；未读取或写入批准文档。"
        : "Sign-off progress check failed; no approval document was read or written.",
    );
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
    await read(
      () => approvalApi.preflight(projectId, runId, assessmentId, approverId),
      (result) => {
        if (result.assessment.assessment_hash !== assessmentHash)
          throw new Error("Assessment hash changed");
        setPreflight(result);
      },
      zh
        ? "预检失败；未写入任何批准或审计。"
        : "Preflight failed; no approval or audit was written.",
    );
  }

  async function record() {
    if (
      !validTarget() ||
      !validApprover() ||
      !confirmed ||
      lock.current ||
      pendingApprovals.has(key)
    )
      return;
    if (decision === "revoked" && !note.trim()) {
      setError(zh ? "撤销必须提供理由。" : "A revocation reason is required.");
      return;
    }
    lock.current = true;
    const at = begin();
    const id = crypto.randomUUID().replaceAll("-", "");
    pendingApprovals.set(key, id);
    setConfirmed(false);
    try {
      const result = await approvalApi.create(projectId, runId, id, {
        assessment_id: assessmentId,
        assessment_hash: assessmentHash,
        expected_previous_revision: Math.max(
          0,
          ...(runRows ?? []).map((row) => row.revision),
          preflight?.latest_approval?.revision ?? 0,
          projectRows?.find((row) => row.run_id === runId)?.revision ?? 0,
        ),
        approver_id: approverId,
        decision,
        ...(note.trim() ? { note: note.trim() } : {}),
        confirmed: true,
      });
      pendingApprovals.delete(key);
      if (at === epoch.current) {
        setRunRows((rows) => [
          {
            id: result.id,
            project_id: result.project_id,
            run_id: result.run_id,
            revision: result.revision,
            created_at_ms: result.created_at_ms,
            assessment_id: result.assessment.id,
            assessment_hash: result.assessment.assessment_hash,
            approver_id: result.approver_id,
            decision: result.decision,
            approval_hash: result.approval_hash,
          },
          ...(rows ?? []),
        ]);
        setAudit(null);
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
        const receipt = await approvalApi.approvalMetadata(
          projectId,
          runId,
          id,
        );
        if (receipt.id === id) {
          pendingApprovals.delete(key);
          if (at === epoch.current) {
            setRunRows(null);
            setAudit(null);
            setProjectRows(null);
            setIntegrity(null);
            setProjectIntegrity(null);
            setSignoff(null);
            setPreflight(null);
          }
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
      finish(at);
    }
  }

  return {
    projectRows,
    runId,
    runRows,
    audit,
    integrity,
    projectIntegrity,
    signoff,
    assessments,
    requiredSignoff,
    capabilities,
    assessmentId,
    assessmentHash,
    approverId,
    decision,
    note,
    confirmed,
    preflight,
    busy,
    error,
    notice,
    pendingId,
    validTarget,
    validApprover,
    loadProject,
    loadRun,
    loadCapabilities,
    loadAssessments,
    checkProjectIntegrity,
    checkIntegrity,
    checkSignoff,
    checkPreflight,
    record,
    setPreflight,
    setConfirmed,
    setError,
    setNotice,
    setSignoff,
    setRunId: edit(setRunId),
    setAssessmentId: edit(setAssessmentId),
    setAssessmentHash: edit(setAssessmentHash),
    setApproverId: edit(setApproverId),
    setRequiredSignoff: editRequiredSignoff,
    setDecision: edit(setDecision),
    setNote: edit(setNote),
  };
}
