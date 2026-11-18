"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import {
  beginAssignment,
  finishAssignment,
  getPendingAssignment,
  lockAssignmentReconciliation,
  unlockAssignmentReconciliation,
  useApprovalRequestPendingRevision,
} from "@/core/evaluation/approval-request-pending";
import { signatureApi } from "@/core/evaluation/approval-requests";
const invalidateEpoch = (epoch: { current: number }) => {
  epoch.current += 1;
};

/** Pending metadata survives project/account changes in page memory only. */
export function ApprovalRequestAssignment({
  projectId,
  runId,
  assessmentId,
  assessmentHash,
  approverId,
  disabled = false,
  zh,
}: {
  projectId: string;
  runId: string;
  assessmentId: string;
  assessmentHash: string;
  approverId: string;
  disabled?: boolean;
  zh: boolean;
}) {
  const { user, isAuthenticated, isLoading } = useAuth();
  useApprovalRequestPendingRevision();
  if (isLoading || !isAuthenticated || !user || user.needs_setup) return null;
  return (
    <AccountAssignment
      key={user.id}
      actor={user.id}
      projectId={projectId}
      runId={runId}
      assessmentId={assessmentId}
      assessmentHash={assessmentHash}
      approverId={approverId}
      disabled={disabled}
      zh={zh}
    />
  );
}

function AccountAssignment({
  actor,
  projectId,
  runId,
  assessmentId,
  assessmentHash,
  approverId,
  disabled: parentDisabled,
  zh,
}: {
  actor: string;
  projectId: string;
  runId: string;
  assessmentId: string;
  assessmentHash: string;
  approverId: string;
  disabled: boolean;
  zh: boolean;
}) {
  const text = (cn: string, en: string) => (zh ? cn : en);
  const [hours, setHours] = useState("24");
  const [shared, setShared] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const alive = useRef(false),
    epoch = useRef(0);
  useLayoutEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      invalidateEpoch(epoch);
    };
  }, []);
  useLayoutEffect(() => {
    epoch.current++;
    setShared(false);
    setConfirmed(false);
    setMessage("");
  }, [projectId, runId, assessmentId, assessmentHash, approverId]);
  const unresolved = getPendingAssignment(actor);
  const disabled = parentDisabled || busy || !!unresolved;
  const valid =
    !!projectId &&
    /^[0-9a-f]{32}$/.test(runId) &&
    /^[0-9a-f]{32}$/.test(assessmentId) &&
    /^[0-9a-f]{64}$/.test(assessmentHash) &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      approverId,
    ) &&
    approverId !== actor &&
    /^\d+$/.test(hours) &&
    Number(hours) >= 1 &&
    Number(hours) <= 720;
  async function create() {
    if (!alive.current || !valid || !shared || !confirmed) return;
    const entry = {
      id: crypto.randomUUID().replaceAll("-", ""),
      projectId,
      runId,
      assessmentId,
      assessmentHash,
      approverId,
      expires: Date.now() + Number(hours) * 3600000,
    };
    if (!beginAssignment(actor, entry)) return;
    setBusy(true);
    setConfirmed(false);
    setShared(false);
    setMessage("");
    const token = epoch.current;
    try {
      const result = await signatureApi.create(projectId, runId, entry.id, {
        assessment_id: assessmentId,
        assessment_hash: assessmentHash,
        approver_id: approverId,
        expires_at_ms: entry.expires,
        share_summary: true,
        confirmed: true,
      });
      finishAssignment(actor, true);
      if (alive.current && epoch.current === token)
        setMessage(
          text(
            `签核请求已创建：${result.id}。请将请求 ID 提供给被指派人，站内通知已保存。`,
            `Signature request created: ${result.id}. The assignee can load their in-app notification.`,
          ),
        );
    } catch {
      if (alive.current && epoch.current === token)
        setMessage(
          text(
            "结果未知；保留原请求 ID，只读对账。",
            "Result unknown; keep the original request ID for read-only reconciliation.",
          ),
        );
    } finally {
      finishAssignment(actor, false);
      if (alive.current) {
        setBusy(false);
      }
    }
  }
  async function reconcile() {
    const entry = getPendingAssignment(actor);
    if (!alive.current || !entry || !lockAssignmentReconciliation(actor))
      return;
    setBusy(true);
    setMessage("");
    const token = epoch.current;
    try {
      const result = await signatureApi.get(entry.id);
      if (
        result.project_id !== entry.projectId ||
        result.run_id !== entry.runId ||
        result.assessment_id !== entry.assessmentId ||
        result.assessment_hash !== entry.assessmentHash ||
        result.approver_id !== entry.approverId ||
        result.expires_at_ms !== entry.expires
      )
        throw new Error("Invalid original assignment");
      finishAssignment(actor, true);
      if (alive.current && epoch.current === token)
        setMessage(
          text(
            `原请求已对账：${result.id} · ${result.status}`,
            `Original assignment reconciled: ${result.id} · ${result.status}`,
          ),
        );
    } catch {
      if (alive.current && epoch.current === token)
        setMessage(
          text(
            "原指派仍未确认；保留原 ID，不重发。",
            "Original assignment remains unresolved; keep its original ID without resending.",
          ),
        );
    } finally {
      unlockAssignmentReconciliation(actor);
      if (alive.current) {
        setBusy(false);
      }
    }
  }
  return (
    <section
      aria-label={text("指派本人签核", "Assign an authenticated signature")}
      className="space-y-3 rounded-lg border p-4"
    >
      <h3 className="font-medium">
        {text("指派本人签核", "Assign an authenticated signature")}
      </h3>
      <p className="text-muted-foreground text-sm">
        {text(
          "使用上方已选运行、评估修订和账号，只向该已初始化用户分享固定汇总。所有使用者均可被指派，不需要单独的审核人角色。",
          "Uses the selected run, assessment revision and account. Only the pinned aggregate is shared; every initialized user can be assigned without a separate reviewer role.",
        )}
      </p>
      <p className="font-mono text-xs break-all">{`${runId || "—"} · ${assessmentId || "—"} · ${assessmentHash || "—"} · ${approverId || "—"}`}</p>
      <label className="block max-w-xs text-sm">
        {text("签署期限（小时，1–720）", "Signing deadline (hours, 1–720)")}
        <Input
          aria-label="Signing deadline hours"
          value={hours}
          disabled={disabled}
          inputMode="numeric"
          onChange={(e) => {
            setHours(e.target.value);
            setShared(false);
            setConfirmed(false);
            setMessage("");
          }}
        />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          aria-label="Share this pinned aggregate summary"
          type="checkbox"
          checked={shared}
          disabled={disabled}
          onChange={(e) => {
            setShared(e.target.checked);
            setConfirmed(false);
          }}
        />
        {text(
          "同意分享本次固定评估的汇总",
          "Share this pinned aggregate summary",
        )}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          aria-label="Confirm signature assignment"
          type="checkbox"
          checked={confirmed}
          disabled={disabled}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        {text("确认向此账号发起签核请求", "Confirm signature assignment")}
      </label>
      <Button
        disabled={disabled || !valid || !shared || !confirmed}
        onClick={() => void create()}
      >
        {text("发起签核指派", "Assign signature request")}
      </Button>
      {unresolved && (
        <div role="status" className="break-all">
          <p>
            {text("原请求 ID", "Original request ID")}: {unresolved.id} ·{" "}
            {unresolved.projectId}
          </p>
          <Button disabled={busy} onClick={() => void reconcile()}>
            {text("按原指派对账", "Reconcile original assignment")}
          </Button>
        </div>
      )}
      {message && (
        <p role="status" className="break-all">
          {message}
        </p>
      )}
    </section>
  );
}
