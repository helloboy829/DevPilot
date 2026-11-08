"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type { ProjectComponent } from "@/core/datasets/registry-types";
import { evaluationApi } from "@/core/evaluation/api";
import type { FrozenPlan } from "@/core/evaluation/plan-types";

type Receipt = {
  id: string;
  run_id: string;
  state: string;
  reservation_held: boolean;
};
type Policy = {
  enabled: boolean;
  max_active_runs: number;
  max_reserved_concurrency: number;
};

/** Key by project. No auto-send, auto-poll, request plaintext or browser storage. */
export function EvaluationExecutionPanel({
  projectId,
  zh,
}: {
  projectId: string;
  zh: boolean;
}) {
  const [components, setComponents] = useState<ProjectComponent[]>([]);
  const [plans, setPlans] = useState<FrozenPlan[]>([]);
  const [componentId, setComponentId] = useState("");
  const [planId, setPlanId] = useState("");
  const [policy, setPolicy] = useState<Policy>();
  const [runs, setRuns] = useState<Receipt[]>([]);
  const [receipt, setReceipt] = useState<Receipt>();
  const [clientKey, setClientKey] = useState("");
  const [authorized, setAuthorized] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const epoch = useRef(0);
  const lock = useRef(false);
  const base = `evaluation/projects/${encodeURIComponent(projectId)}`;
  const selected = plans.find((row) => row.id === planId);
  const text = (cn: string, en: string) => (zh ? cn : en);
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  function revoke() {
    setAuthorized(false);
    setConfirmed(false);
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
        if (writing) setBlocked(true);
        setError(
          text(
            "操作未确认。请核对同一个执行编号的收据；不会自动重试、生成新编号或重复发送请求。检查权限、运营配置、加密密钥、冻结版本及配额。",
            "Operation unconfirmed. Inspect the SAME execution identifier; no automatic retry, new identifier or repeated request. Check permissions, operator policy, storage key, frozen versions and quota.",
          ),
        );
      }
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  async function load(token: number) {
    const [config, catalog, rows] = await Promise.all([
      evaluationApi<Policy>(base + "/execution-policy"),
      evaluationApi<{ components: ProjectComponent[] }>(base + "/components"),
      evaluationApi<{ executions: Receipt[] }>(base + "/execution-runs"),
    ]);
    if (token !== epoch.current) return;
    setPolicy(config);
    setComponents(catalog.components);
    setRuns(rows.executions);
  }
  async function loadPlans(token: number) {
    const result = await evaluationApi<{ plans: FrozenPlan[] }>(
      base + "/components/" + encodeURIComponent(componentId) + "/plans",
    );
    if (token === epoch.current) setPlans(result.plans);
  }
  async function queue(token: number) {
    if (
      !selected ||
      !policy?.enabled ||
      !authorized ||
      !confirmed ||
      blocked ||
      clientKey
    )
      return;
    // Assigned BEFORE the first write. An ambiguous response never creates a new key.
    const key = crypto.randomUUID().replaceAll("-", "");
    setClientKey(key);
    setBlocked(true);
    const result = await evaluationApi<Receipt>(
      base + "/execution-runs/" + key,
      {
        plan_id: selected.id,
        plan_hash: selected.definition_hash,
        confirmed: true,
        target_authorized: true,
      },
      "PUT",
    );
    if (token === epoch.current) setReceipt(result);
  }
  async function inspect(token: number) {
    const result = await evaluationApi<Receipt>(
      base + "/execution-runs/" + clientKey,
    );
    if (token === epoch.current) setReceipt(result);
  }
  async function cancel(token: number) {
    if (!receipt) return;
    const result = await evaluationApi<Receipt>(
      base + "/execution-runs/" + receipt.id + "/cancel",
      {},
      "POST",
    );
    if (token === epoch.current) setReceipt(result);
  }
  const selectStyle =
    "bg-background w-full rounded-md border px-3 py-2 text-sm";
  return (
    <section
      aria-label={text("授权评测执行", "Authorized evaluation execution")}
      className="space-y-4 rounded-xl border p-5"
    >
      <h2 className="text-lg font-semibold">
        {text(
          "执行评测 · 独立授权",
          "Execute evaluation · separate authorization",
        )}
      </h2>
      <p className="text-muted-foreground text-sm">
        {text(
          "仅支持冻结的 QA JSON 计划。先确认目标调用授权和计划预算，再显式入队。采集完成不代表效果通过；实际答案进入下方人工复核。非流式接口不计算 TTFT。",
          "Frozen QA JSON plans only. Confirm target authorization and frozen budgets before explicitly queuing. Collected output is NOT a quality PASS; review actual answers below. No TTFT for non-streaming responses.",
        )}
      </p>
      <fieldset disabled={busy} className="space-y-4">
        <Button variant="outline" onClick={() => void operate(load)}>
          {text("加载执行工作区", "Load execution workspace")}
        </Button>
        {policy && (
          <p className="text-sm">
            {policy.enabled
              ? text("运营方已启用执行", "Execution enabled by operator")
              : text(
                  "运营方尚未启用执行；不会自动开启或生成密钥",
                  "Execution disabled by operator; no implicit activation or key generation",
                )}{" "}
            · {text("全局运行/并发上限", "Global run / concurrency limits")}:{" "}
            {policy.max_active_runs} / {policy.max_reserved_concurrency}
          </p>
        )}
        <label className="block space-y-1">
          <span>{text("执行组件", "Execution component")}</span>
          <select
            className={selectStyle}
            value={componentId}
            disabled={!!clientKey}
            onChange={(event) => {
              setComponentId(event.target.value);
              setPlanId("");
              setPlans([]);
              revoke();
            }}
          >
            <option value="">—</option>
            {components.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name_at_link}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="outline"
          disabled={!componentId || !!clientKey}
          onClick={() => void operate(loadPlans)}
        >
          {text("加载可执行计划", "Load executable plans")}
        </Button>
        <label className="block space-y-1">
          <span>{text("执行计划", "Execution plan")}</span>
          <select
            className={selectStyle}
            value={planId}
            disabled={!!clientKey}
            onChange={(event) => {
              setPlanId(event.target.value);
              revoke();
            }}
          >
            <option value="">—</option>
            {plans.map((row) => (
              <option key={row.id} value={row.id}>
                {row.version_label}
              </option>
            ))}
          </select>
        </label>
        {selected && (
          <div className="rounded border p-3 text-sm break-all">
            <p>
              {text("冻结计划哈希", "Frozen plan hash")}:{" "}
              {selected.definition_hash}
            </p>
            <p>
              {selected.definition.limits.mode} · {text("请求数", "Requests")}:{" "}
              {selected.definition.limits.request_count} ·{" "}
              {text("并发", "Concurrency")}:{" "}
              {selected.definition.limits.concurrency} ·{" "}
              {text("请求/整体时限(ms)", "Attempt / run deadline (ms)")}:{" "}
              {selected.definition.limits.timeout_ms} /{" "}
              {selected.definition.limits.wall_time_ms}
            </p>
          </div>
        )}
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={authorized}
            onChange={(event) => setAuthorized(event.target.checked)}
          />
          <span>
            {text(
              "我有权调用此目标组件，并已获得数据使用及压测授权。",
              "I am authorized to call this target, use these data and apply the planned load.",
            )}
          </span>
        </label>
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            {text(
              "我确认冻结计划、样本、并发及预算；了解未知送达不重试。",
              "I confirm the frozen plan, samples, concurrency and budgets; uncertain delivery is never retried.",
            )}
          </span>
        </label>
        <Button
          disabled={
            !selected ||
            !policy?.enabled ||
            !authorized ||
            !confirmed ||
            blocked ||
            !!clientKey
          }
          onClick={() => void operate(queue, true)}
        >
          {text("授权并加入执行队列", "Authorize and queue execution")}
        </Button>
        {clientKey && (
          <div className="space-y-2 rounded border p-3 text-sm break-all">
            <p>
              {text("本次客户端执行编号", "Client execution identifier")}:{" "}
              {clientKey}
            </p>
            <Button variant="outline" onClick={() => void operate(inspect)}>
              {text("核对执行收据", "Inspect execution receipt")}
            </Button>
            <p>
              {text(
                "本页不会再创建第二次执行。未知结果请保留此编号；离开页面前记录，避免重复调用。",
                "This page will not create a second execution. Keep this identifier when the outcome is uncertain, including before leaving the page.",
              )}
            </p>
          </div>
        )}
        {receipt && (
          <div className="space-y-2 rounded border p-3 text-sm break-all">
            <p>
              {text("执行收据", "Execution receipt")}: {receipt.id} ·{" "}
              {receipt.state}
            </p>
            <p>
              {text("结果复核运行编号", "Review run")}: {receipt.run_id}
            </p>
            <p>
              {receipt.reservation_held
                ? text(
                    "配额仍预留；取消或超时不代表网络请求已停止。失联 Worker 不自动释放配额。",
                    "Quota held; cancellation / timeout does not prove network delivery stopped. Lost workers do not automatically release quota.",
                  )
                : text(
                    "本应用 Worker 已结束或未开始调用；不是业务验收结论。",
                    "Application worker drained or never dispatched; not a business acceptance verdict.",
                  )}
            </p>
            {["queued", "running", "cancel_requested"].includes(
              receipt.state,
            ) && (
              <Button
                variant="outline"
                onClick={() => void operate(cancel, true)}
              >
                {text("取消当前执行", "Cancel this execution")}
              </Button>
            )}
          </div>
        )}
        {runs.length > 0 && (
          <div>
            <h3>
              {text(
                "最近执行（点击仅查看）",
                "Recent executions (inspect only)",
              )}
            </h3>
            <ul className="space-y-2">
              {runs.map((row) => (
                <li key={row.id}>
                  <Button
                    variant="outline"
                    onClick={() => {
                      revoke();
                      setBlocked(true);
                      setClientKey(row.id);
                      setReceipt(row);
                    }}
                  >
                    {row.id} · {row.state}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </fieldset>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </section>
  );
}
