"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/core/auth/AuthProvider";
import {
  loadReservationSnapshot,
  reservationStates,
  type ReservationSnapshot,
} from "@/core/evaluation/execution-operations";

export function ExecutionOperationsPanel({ zh }: { zh: boolean }) {
  const { user, isAuthenticated, isLoading } = useAuth();
  // Unmount account-scoped state during logout, role loss and auth refresh.
  // This role gate is presentation only; the server enforces admin + permission.
  if (isLoading || !isAuthenticated || user?.system_role !== "admin")
    return (
      <p role="status">
        {zh
          ? "仅管理员可手动查看；请先确认登录身份。"
          : "Administrators only; confirm your signed-in identity first."}
      </p>
    );
  return <AccountSnapshot key={user.id} zh={zh} />;
}

function AccountSnapshot({ zh }: { zh: boolean }) {
  const [snapshot, setSnapshot] = useState<ReservationSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const alive = useRef(false);
  const locked = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useLayoutEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      controller.current?.abort();
    };
  }, []);
  async function load() {
    if (!alive.current || locked.current) return;
    locked.current = true;
    const request = new AbortController();
    controller.current = request;
    setSnapshot(null);
    setFailed(false);
    setBusy(true);
    const current = () =>
      alive.current &&
      controller.current === request &&
      !request.signal.aborted;
    try {
      const result = await loadReservationSnapshot(request.signal);
      if (current()) setSnapshot(result);
    } catch {
      if (current()) setFailed(true);
    } finally {
      if (current()) {
        locked.current = false;
        controller.current = null;
        setBusy(false);
      }
    }
  }
  const labels = zh
    ? {
        queued: "排队",
        running: "运行中",
        cancel_requested: "已请求取消",
        collected: "采集结束",
        interrupted: "中断",
      }
    : {
        queued: "Queued",
        running: "Running",
        cancel_requested: "Cancellation requested",
        collected: "Collected",
        interrupted: "Interrupted",
      };
  return (
    <section
      className="w-full space-y-4"
      aria-label={zh ? "执行预留只读诊断" : "Read-only execution reservations"}
    >
      <p>
        {zh
          ? "仅按下按钮后读取全局汇总。不轮询、不自动重试、不显示账号、运行或证据明细。"
          : "Loads global aggregates only on click. No polling, automatic retry, account/run identifiers or evidence details."}
      </p>
      <div className="space-y-2 rounded-md border p-3 text-sm">
        <p>
          {zh
            ? "达到截止时间不代表 Worker 或远端处理已经停止。中断记录仍可能持有预留；此页不能释放、回收、重试或发送。"
            : "A reached deadline does not prove the Worker or remote processing has stopped. Interrupted runs may still hold reservations; this page cannot release, reclaim, retry or dispatch."}
        </p>
        <p>
          {zh
            ? "策略仅属于响应进程，不代表所有进程一致或可用配额。观察时间在查询前采集，不是心跳或存活证明。"
            : "Policy belongs only to the serving process, not global agreement or available quota. Observation time is sampled before the query, not a heartbeat or proof of liveness."}
        </p>
      </div>
      <Button type="button" disabled={busy} onClick={() => void load()}>
        {zh ? "手动加载预留快照" : "Load reservation snapshot"}
      </Button>
      {busy && <p role="status">{zh ? "正在加载…" : "Loading…"}</p>}
      {failed && (
        <p role="alert">
          {zh
            ? "诊断暂不可用。未自动重试；如需再次读取，请手动加载。"
            : "Diagnostics unavailable. No automatic retry; load manually for another read."}
        </p>
      )}
      {snapshot && (
        <div data-testid="reservation-snapshot" className="space-y-4">
          <p>
            {zh
              ? "查询前观察时间（Unix 毫秒）"
              : "Pre-query observation time (Unix ms)"}
            : <span>{snapshot.observed_at_ms}</span>
          </p>
          <h2 className="font-semibold">
            {zh
              ? "当前持有预留（全局汇总）"
              : "Held reservations (global aggregates)"}
          </h2>
          <dl className="grid gap-2 sm:grid-cols-2">
            {(
              [
                [
                  zh ? "持有预留运行数" : "Held runs",
                  snapshot.reservations.held_runs,
                ],
                [
                  zh ? "已预留并发" : "Reserved concurrency",
                  snapshot.reservations.reserved_concurrency,
                ],
                [
                  zh ? "已预留请求体字节" : "Reserved body bytes",
                  snapshot.reservations.reserved_body_bytes,
                ],
                [
                  zh ? "已预留响应字节" : "Reserved response bytes",
                  snapshot.reservations.reserved_response_bytes,
                ],
                [
                  zh
                    ? "已达截止时间运行数（非释放许可）"
                    : "Deadline reached runs (not release permission)",
                  snapshot.reservations.deadline_reached_runs,
                ],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd className="font-mono">{value}</dd>
              </div>
            ))}
          </dl>
          <ul className="space-y-1">
            {reservationStates.map((state) => (
              <li key={state}>
                {labels[state]}: {snapshot.states[state].held_runs} /{" "}
                {zh ? "其中已达截止时间" : "deadline reached"}:{" "}
                {snapshot.states[state].deadline_reached_runs}
              </li>
            ))}
          </ul>
          <h2 className="font-semibold">
            {zh
              ? "仅响应进程的策略上限（不是剩余配额）"
              : "Serving-process policy limits (not remaining quota)"}
          </h2>
          <dl className="grid gap-2 sm:grid-cols-2">
            {(
              [
                [
                  zh ? "执行开关" : "Execution enabled",
                  snapshot.policy.enabled
                    ? zh
                      ? "开启"
                      : "Yes"
                    : zh
                      ? "关闭"
                      : "No",
                ],
                [
                  zh ? "最大活动运行数" : "Max active runs",
                  snapshot.policy.max_active_runs,
                ],
                [
                  zh ? "最大预留并发" : "Max reserved concurrency",
                  snapshot.policy.max_reserved_concurrency,
                ],
                [
                  zh ? "单响应最大字节" : "Max response bytes",
                  snapshot.policy.max_response_bytes,
                ],
                [
                  zh ? "最大预留请求体字节" : "Max reserved body bytes",
                  snapshot.policy.max_reserved_body_bytes,
                ],
                [
                  zh ? "最大预留响应字节" : "Max reserved response bytes",
                  snapshot.policy.max_reserved_response_bytes,
                ],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd className="font-mono">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
