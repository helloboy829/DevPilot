"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/core/auth/AuthProvider";
import {
  beginSignature,
  finishSignature,
  getPendingSignature,
  lockSignatureRead,
  lockSignatureReconciliation,
  unlockSignatureRead,
  unlockSignatureReconciliation,
  type SignaturePending,
  useApprovalRequestPendingRevision,
} from "@/core/evaluation/approval-request-pending";
import {
  signatureApi,
  type SignatureNotices,
  type SignatureRequest,
  type SignatureState,
  type SignatureSummaryView,
} from "@/core/evaluation/approval-requests";
const validId = (value: string) => /^[0-9a-f]{32}$/.test(value);
const invalidateEpoch = (epoch: { current: number }) => {
  epoch.current++;
};

/** All initialized members may sign; state and pending receipts remain account scoped. */
export function ApprovalSignatureCenter({ zh }: { zh: boolean }) {
  const { user, isAuthenticated, isLoading } = useAuth();
  useApprovalRequestPendingRevision();
  if (isLoading || !isAuthenticated || !user || user.needs_setup)
    return (
      <p role="status">
        {zh
          ? "请登录并完成账号初始化。"
          : "Sign in and complete account initialization."}
      </p>
    );
  return <AccountSignatures key={user.id} actor={user.id} zh={zh} />;
}

function AccountSignatures({ actor, zh }: { actor: string; zh: boolean }) {
  const text = (cn: string, en: string) => (zh ? cn : en);
  const [requestId, setRequestId] = useState(
    getPendingSignature(actor)?.source.id ?? "",
  );
  const [rows, setRows] = useState<SignatureRequest[] | null>(null);
  const [notices, setNotices] = useState<SignatureNotices | null>(null);
  const [snapshot, setSnapshot] = useState<SignatureState | null>(null);
  const [view, setView] = useState<SignatureSummaryView | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const alive = useRef(false);
  const epoch = useRef(0);
  useLayoutEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      invalidateEpoch(epoch);
    };
  }, []);
  const unresolved = getPendingSignature(actor);
  const source = snapshot?.request;
  const mine = source?.approver_id === actor;
  const enabled = !busy && !unresolved;
  const current = (token: number) => alive.current && epoch.current === token;

  function select(id: string) {
    if (busy || unresolved) return;
    epoch.current++;
    setRequestId(id);
    setSnapshot(null);
    setView(null);
    setConfirmed(false);
    setNote("");
    setMessage("");
  }
  async function read(action: () => Promise<void>) {
    if (!alive.current || getPendingSignature(actor)) return;
    if (!enabled) return;
    if (!lockSignatureRead(actor)) return;
    setBusy(true);
    setMessage("");
    setConfirmed(false);
    try {
      await action();
    } catch {
      if (alive.current)
        setMessage(
          text(
            "读取失败；请核对原请求并明确刷新。",
            "Read failed; check the original request and explicitly refresh.",
          ),
        );
    } finally {
      unlockSignatureRead(actor);
      if (alive.current) setBusy(false);
    }
  }
  async function loadRequest() {
    const token = epoch.current;
    setSnapshot(null);
    setView(null);
    await read(async () => {
      const result = await signatureApi.state(requestId);
      if (current(token)) setSnapshot(result);
    });
  }
  async function write(kind: SignaturePending["kind"]) {
    if (!alive.current || !enabled || !source || !snapshot) return;
    if (
      kind === "view" &&
      (!mine ||
        source.status !== "pending" ||
        snapshot.effectiveness.status !== "pending")
    )
      return;
    if (kind !== "view" && !confirmed) return;
    if (
      kind === "approved" &&
      (!mine ||
        !view ||
        source.status !== "pending" ||
        snapshot.effectiveness.status !== "pending" ||
        Date.now() >= Math.min(source.expires_at_ms, view.expires_at_ms))
    )
      return;
    if (
      kind === "revoked" &&
      (!mine || source.status !== "approved" || !note.trim())
    )
      return;
    if (kind === "cancelled" && (mine || source.status !== "pending")) return;
    const operation = {
      kind,
      id: crypto.randomUUID().replaceAll("-", ""),
      source,
      state: snapshot,
    };
    if (!beginSignature(actor, operation)) return;
    setBusy(true);
    setConfirmed(false);
    setMessage("");
    const token = epoch.current;
    try {
      if (kind === "view") {
        const result = await signatureApi.open(source, operation.id);
        finishSignature(actor, true);
        if (current(token)) setView(result);
      } else {
        const result =
          kind === "cancelled"
            ? await signatureApi.cancel(source, operation.id)
            : await signatureApi.decide(
                source,
                operation.id,
                kind,
                snapshot.approval_revision,
                kind === "approved" ? view!.view_id : undefined,
                kind === "revoked" ? note.trim() : undefined,
              );
        finishSignature(actor, true);
        if (current(token)) {
          setSnapshot(null);
          setView(null);
          setRows(null);
          setNotices(null);
          setNote("");
          setMessage(
            text(
              `已记录 ${result.status}；请明确刷新状态。`,
              `Recorded ${result.status}; explicitly reload the state.`,
            ),
          );
        }
      }
    } catch {
      if (current(token))
        setMessage(
          text(
            "结果未知；只按原 ID 对账，不可重发。",
            "Result unknown; reconcile the original ID without resending.",
          ),
        );
    } finally {
      finishSignature(actor, false);
      if (current(token)) {
        setBusy(false);
      }
    }
  }
  async function reconcile() {
    const operation = getPendingSignature(actor);
    if (!operation || busy || !lockSignatureReconciliation(actor)) return;
    setBusy(true);
    setMessage("");
    setConfirmed(false);
    const token = epoch.current;
    try {
      if (operation.kind === "view") {
        const result = await signatureApi.view(operation.source, operation.id);
        finishSignature(actor, true);
        if (current(token)) {
          setRequestId(operation.source.id);
          setSnapshot(operation.state);
          setView(result);
        }
      } else {
        const result = await signatureApi.operation(
          operation.source.id,
          operation.id,
        );
        if (
          result.subject_hash !== operation.source.subject_hash ||
          result.status !== operation.kind ||
          result.revision !== operation.source.revision + 1 ||
          (operation.kind !== "cancelled" &&
            result.latest_approval_id !== operation.id)
        )
          throw new Error("Invalid operation receipt");
        finishSignature(actor, true);
        if (current(token)) {
          setRequestId(operation.source.id);
          setSnapshot(null);
          setView(null);
          setRows(null);
          setNotices(null);
          setMessage(
            text(
              "原 ID 已对账；请明确刷新当前状态。",
              "Original ID reconciled; explicitly reload current state.",
            ),
          );
        }
      }
    } catch {
      if (current(token))
        setMessage(
          text(
            "原操作仍未确认；保留原 ID，不重发。",
            "Original operation remains unresolved; keep the original ID without resending.",
          ),
        );
    } finally {
      unlockSignatureReconciliation(actor);
      if (current(token)) {
        setBusy(false);
      }
    }
  }
  return (
    <section
      aria-label={text(
        "本人签核与站内通知",
        "My signatures and in-app notifications",
      )}
      className="mb-6 space-y-4 rounded-lg border p-4"
    >
      <h2 className="font-medium">
        {text("本人签核与站内通知", "My signatures and in-app notifications")}
      </h2>
      <p className="text-muted-foreground text-sm">
        {text(
          "所有用户均可接受指派。签核只共享固定评估汇总；本人签署与项目 owner 的历史代录分别记录。",
          "Every member can receive assignments. Signatures share a pinned assessment summary; your own signature is distinguished from historical owner-recorded decisions.",
        )}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={!enabled}
          onClick={() => {
            const token = epoch.current;
            void read(async () => {
              setRows(null);
              const result = await signatureApi.inbox(actor);
              if (current(token)) {
                setRows(result.requests);
                if (result.truncated)
                  setMessage(
                    text(
                      "仅显示最新 100 项；其他请求请使用原 ID。",
                      "Showing the latest 100 requests; use the original ID for others.",
                    ),
                  );
              }
            });
          }}
        >
          {text("加载我的签核请求", "Load my signature requests")}
        </Button>
        <Button
          disabled={!enabled}
          onClick={() => {
            const token = epoch.current;
            void read(async () => {
              setNotices(null);
              const result = await signatureApi.notifications();
              if (current(token)) setNotices(result);
            });
          }}
        >
          {text("加载站内通知", "Load in-app notifications")}
        </Button>
      </div>
      {rows && (
        <ul className="space-y-1">
          {rows.map((row) => (
            <li key={row.id}>
              <Button
                variant="outline"
                disabled={!enabled}
                aria-label={`Select signature ${row.id}`}
                onClick={() => select(row.id)}
              >
                {row.id} · {row.status}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {notices && (
        <div>
          <ul>
            {notices.notifications.map((item) => (
              <li
                key={`${item.request_id}:${item.revision}`}
                className="text-sm break-all"
              >
                {item.request_id} · {item.action} ·{" "}
                {new Date(item.at_ms).toISOString()}
              </li>
            ))}
          </ul>
          {notices.truncated && (
            <p>
              {text(
                "仅显示最新 100 条站内事件。",
                "Showing the latest 100 in-app events.",
              )}
            </p>
          )}
        </div>
      )}
      <label className="block text-sm">
        {text("签核请求 ID", "Signature request ID")}
        <Input
          aria-label="Signature request ID"
          value={requestId}
          disabled={busy || !!unresolved}
          onChange={(event) => select(event.target.value)}
        />
      </label>
      <Button
        disabled={!enabled || !validId(requestId)}
        onClick={() => void loadRequest()}
      >
        {text("加载签核请求", "Load signature request")}
      </Button>
      {unresolved && (
        <div role="status">
          <p className="break-all">
            {text("原操作 ID", "Original operation ID")}: {unresolved.id}
          </p>
          <Button disabled={busy} onClick={() => void reconcile()}>
            {text("按原操作对账", "Reconcile original operation")}
          </Button>
        </div>
      )}
      {source && (
        <div className="space-y-2 text-sm break-all">
          <p>
            {text("固定评估", "Pinned assessment")}: {source.assessment_id} ·{" "}
            {source.assessment_hash}
          </p>
          <p>
            {text("当前生效状态", "Current effectiveness")}:{" "}
            <span data-testid="signature-effectiveness">
              {snapshot.effectiveness.status}
            </span>
          </p>
          <p>{snapshot.effectiveness.blockers.join(", ")}</p>
          <p>
            {text("签署截止", "Signing deadline")}:{" "}
            {new Date(source.expires_at_ms).toISOString()}
          </p>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={
            !enabled ||
            !source ||
            !mine ||
            source.status !== "pending" ||
            snapshot?.effectiveness.status !== "pending"
          }
          onClick={() => void write("view")}
        >
          {text("打开指派汇总", "Open assigned summary")}
        </Button>
      </div>
      {view && (
        <div className="rounded border p-3 text-sm">
          <p>
            {text("人工 PASS / ALL", "Human PASS / ALL")}:{" "}
            <span data-testid="signature-all-rate">
              {view.summary.human_pass_rate.numerator} /{" "}
              {view.summary.human_pass_rate.denominator}
            </span>
          </p>
          <p>
            {text("冻结阈值", "Frozen criteria")}:{" "}
            {view.summary.criteria.status}
          </p>
          <p>
            {text("汇总完整性", "Summary hash")}:{" "}
            <span className="break-all">{view.summary.summary_hash}</span>
          </p>
        </div>
      )}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          aria-label="I confirm my own signature"
          checked={confirmed}
          disabled={!enabled || !source}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        {text(
          "我确认本人的签署、撤销或取消决定",
          "I confirm my own signature, revocation or cancellation",
        )}
      </label>
      <label className="block text-sm">
        {text("撤销理由", "Revocation reason")}
        <Textarea
          value={note}
          maxLength={2000}
          disabled={!enabled}
          onChange={(event) => {
            setNote(event.target.value);
            setConfirmed(false);
          }}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          disabled={
            !enabled ||
            !mine ||
            !confirmed ||
            !view ||
            source?.status !== "pending" ||
            snapshot?.effectiveness.status !== "pending"
          }
          onClick={() => void write("approved")}
        >
          {text("签署本次评估", "Sign this assessment")}
        </Button>
        <Button
          variant="outline"
          disabled={
            !enabled ||
            !mine ||
            !confirmed ||
            source?.status !== "approved" ||
            !note.trim()
          }
          onClick={() => void write("revoked")}
        >
          {text("撤销本人签署", "Revoke my signature")}
        </Button>
        <Button
          variant="outline"
          disabled={
            !enabled || mine || !confirmed || source?.status !== "pending"
          }
          onClick={() => void write("cancelled")}
        >
          {text("取消待签请求", "Cancel pending request")}
        </Button>
      </div>
      {message && <p role="status">{message}</p>}
    </section>
  );
}
