"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { EvaluationProject } from "@/core/datasets/types";
import { evaluationApi } from "@/core/evaluation/api";
import type {
  PendingRetest,
  RetestArchive,
  RetestCase,
  RetestEvidence,
  RetestMetadata,
  RetestTransition,
} from "@/core/evaluation/retest-types";
import type {
  ReviewCase,
  ReviewRun,
  ReviewSummary,
} from "@/core/evaluation/review-types";

const selectStyle =
  "bg-background w-full min-w-0 rounded-md border px-3 py-2 text-sm";
const idPattern = /^[0-9a-f]{32}$/;
const hashPattern = /^[0-9a-f]{64}$/;
function validSummary(s: ReviewSummary, projectId: string, runId: string) {
  return (
    s.schema === "qa-human-summary.v1" &&
    s.scope === "verified_human_summary_preview" &&
    s.project_id === projectId &&
    s.run_id === runId &&
    hashPattern.test(s.summary_hash) &&
    s.acceptance === "not_approved" &&
    s.readiness === "review_complete" &&
    s.blockers.length === 0 &&
    s.human_pass_rate.denominator >= 1 &&
    s.human_pass_rate.denominator <= 500 &&
    s.counts.pass + s.counts.fail === s.human_pass_rate.denominator &&
    s.counts.uncertain === 0 &&
    s.counts.unreviewed === 0
  );
}

/** Pending write receipts survive project switches in this page's memory only. */
export function EvaluationRetestPanel({ zh }: { zh: boolean }) {
  const [projects, setProjects] = useState<EvaluationProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [pending, setPending] = useState<Record<string, PendingRetest | null>>(
    {},
  );
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
  async function load() {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError(false);
    try {
      const data = await evaluationApi<{ projects: EvaluationProject[] }>(
        "evaluation/projects",
      );
      if (token === epoch.current) setProjects(data.projects);
    } catch {
      if (token === epoch.current) setError(true);
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  return (
    <section
      aria-label={zh ? "整改复测" : "Remediation & retesting"}
      className="space-y-4"
    >
      <h2 className="text-lg font-semibold">
        {zh ? "同基准整改复测" : "Same-benchmark retest comparisons"}
      </h2>
      <p className="text-muted-foreground text-sm">
        {zh
          ? "选择同组件前后两个已完成人工复核的效果运行。服务器严格核验数据、映射、预算和判定口径；逐条记录修复与退化，不自动判定验收。此处不执行测试、不调用模型。"
          : "Compare two fully human-reviewed effectiveness runs of one component. The server verifies identical frozen data, mappings, budgets and judgment policy, then archives fixes and regressions. No test execution, model calls or automatic acceptance."}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Button variant="outline" disabled={busy} onClick={() => void load()}>
          {zh ? "加载项目" : "Load projects"}
        </Button>
        <label className="min-w-0 flex-1 space-y-1 text-sm">
          {zh ? "复测项目" : "Retest project"}
          <select
            aria-label={zh ? "复测项目" : "Retest project"}
            className={selectStyle}
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
          >
            <option value="">{zh ? "选择项目" : "Choose project"}</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p role="alert">
          {zh
            ? "项目读取失败，请核对权限。"
            : "Could not load projects; check permissions."}
        </p>
      )}
      {projectId && (
        <RetestWorkspace
          key={projectId + String(zh)}
          projectId={projectId}
          zh={zh}
          initialPending={pending[projectId] ?? null}
          onPending={(value) =>
            setPending((old) => ({ ...old, [projectId]: value }))
          }
        />
      )}
    </section>
  );
}

function RetestWorkspace({
  projectId,
  zh,
  initialPending,
  onPending,
}: {
  projectId: string;
  zh: boolean;
  initialPending: PendingRetest | null;
  onPending: (value: PendingRetest | null) => void;
}) {
  const [runs, setRuns] = useState<ReviewRun[]>([]);
  const [baselineId, setBaselineId] = useState("");
  const [retestId, setRetestId] = useState("");
  const [summaries, setSummaries] = useState<
    [ReviewSummary, ReviewSummary] | null
  >(null);
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(initialPending);
  const [archive, setArchive] = useState<RetestArchive | null>(null);
  const [history, setHistory] = useState<RetestMetadata[]>([]);
  const [openId, setOpenId] = useState("");
  const [filter, setFilter] = useState<RetestTransition | "all">("all");
  const [evidence, setEvidence] = useState<RetestEvidence | null>(null);
  const evidenceEpoch = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const epoch = useRef(0);
  const lock = useRef(false);
  const root = "evaluation/projects/" + encodeURIComponent(projectId);
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  async function operate(task: (current: () => boolean) => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError(false);
    setEvidence(null);
    try {
      await task(() => token === epoch.current);
    } catch {
      if (token === epoch.current) setError(true);
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  function invalidate() {
    setSummaries(null);
    setConfirmed(false);
    setArchive(null);
    setEvidence(null);
  }
  function checked(result: RetestArchive, id: string, receipt?: PendingRetest) {
    if (
      result.schema !== "qa-retest-archive.v1" ||
      result.scope !== "same_benchmark_human_comparison" ||
      result.project_id !== projectId ||
      result.id !== id ||
      result.acceptance !== "not_approved" ||
      !hashPattern.test(result.archive_hash) ||
      !validSummary(result.baseline, projectId, result.baseline.run_id) ||
      !validSummary(result.retest, projectId, result.retest.run_id) ||
      result.baseline.component_id !== result.retest.component_id ||
      result.cases.length !== result.baseline.human_pass_rate.denominator ||
      result.cases.length !== result.retest.human_pass_rate.denominator
    )
      throw new Error("Invalid comparison receipt");
    if (
      receipt &&
      (result.baseline.run_id !== receipt.baseline.run_id ||
        result.baseline.summary_hash !== receipt.baseline.summary_hash ||
        result.retest.run_id !== receipt.retest.run_id ||
        result.retest.summary_hash !== receipt.retest.summary_hash)
    )
      throw new Error("Mismatched comparison receipt");
    return result;
  }
  const labels: Record<RetestTransition, string> = {
    fail_to_pass: zh ? "已修复（不通过 → 通过）" : "Fixed (fail → pass)",
    pass_to_fail: zh ? "发生退化（通过 → 不通过）" : "Regressed (pass → fail)",
    pass_to_pass: zh ? "保持通过" : "Still passing",
    fail_to_fail: zh ? "仍未通过" : "Still failing",
  };
  function loadRuns() {
    void operate(async (current) => {
      invalidate();
      setRuns([]);
      setBaselineId("");
      setRetestId("");
      const data = await evaluationApi<{ runs: ReviewRun[] }>(
        root + "/review-runs",
      );
      if (current()) setRuns(data.runs);
    });
  }
  function verify() {
    void operate(async (current) => {
      invalidate();
      const before = await evaluationApi<ReviewSummary>(
        root + "/review-runs/" + encodeURIComponent(baselineId) + "/summary",
      );
      if (!current()) return;
      const after = await evaluationApi<ReviewSummary>(
        root + "/review-runs/" + encodeURIComponent(retestId) + "/summary",
      );
      if (
        !validSummary(before, projectId, baselineId) ||
        !validSummary(after, projectId, retestId) ||
        before.component_id !== after.component_id
      )
        throw new Error("Incomplete review");
      if (current()) setSummaries([before, after]);
    });
  }
  function create() {
    if (!summaries || !confirmed || pending || baselineId === retestId) return;
    const viewed = summaries;
    void operate(async (current) => {
      const receipt: PendingRetest = {
        id: crypto.randomUUID().replaceAll("-", ""),
        baseline: {
          run_id: viewed[0].run_id,
          summary_hash: viewed[0].summary_hash,
        },
        retest: {
          run_id: viewed[1].run_id,
          summary_hash: viewed[1].summary_hash,
        },
      };
      // Persist pending ID in parent memory BEFORE network; no automatic resend.
      setPending(receipt);
      onPending(receipt);
      setConfirmed(false);
      setArchive(null);
      const data = checked(
        await evaluationApi<RetestArchive>(
          root + "/retest-archives/" + receipt.id,
          {
            baseline: receipt.baseline,
            retest: receipt.retest,
            confirmed: true,
          },
          "PUT",
        ),
        receipt.id,
        receipt,
      );
      if (current()) {
        setArchive(data);
        setPending(null);
        onPending(null);
        setOpenId(data.id);
      }
    });
  }
  function reconcile() {
    if (!pending) return;
    const receipt = pending;
    void operate(async (current) => {
      const data = checked(
        await evaluationApi<RetestArchive>(
          root + "/retest-archives/" + receipt.id,
        ),
        receipt.id,
        receipt,
      );
      if (current()) {
        setArchive(data);
        setPending(null);
        onPending(null);
        setOpenId(data.id);
        setSummaries(null);
        setConfirmed(false);
      }
    });
  }
  function open() {
    if (!idPattern.test(openId)) return;
    void operate(async (current) => {
      setArchive(null);
      setSummaries(null);
      setConfirmed(false);
      const data = checked(
        await evaluationApi<RetestArchive>(root + "/retest-archives/" + openId),
        openId,
      );
      if (current()) {
        setArchive(data);
        setFilter("all");
      }
    });
  }
  function loadHistory() {
    void operate(async (current) => {
      const data = await evaluationApi<{ comparisons: RetestMetadata[] }>(
        root + "/retest-archives",
      );
      if (current()) setHistory(data.comparisons);
    });
  }
  function openEvidence(row: RetestCase) {
    if (!archive) return;
    const frozen = archive;
    void operate(async (current) => {
      const generation = ++evidenceEpoch.current;
      const relevant = () => current() && generation === evidenceEpoch.current;
      const pair: ReviewCase[] = [];
      for (const side of ["baseline", "retest"] as const) {
        if (!relevant()) return;
        const data = await evaluationApi<ReviewCase>(
          root +
            "/review-runs/" +
            frozen[side].run_id +
            "/cases/" +
            row.ordinal,
        );
        if (
          data.scope !== "human_review_only" ||
          data.run_id !== frozen[side].run_id ||
          data.ordinal !== row.ordinal ||
          data.sample_id !== row.sample_id ||
          data.case_hash !==
            row[
              (side + "_case_hash") as "baseline_case_hash" | "retest_case_hash"
            ] ||
          data.review_revision <
            row[(side + "_revision") as "baseline_revision" | "retest_revision"]
        )
          throw new Error("Evidence changed");
        pair.push(data);
      }
      if (
        pair[0]!.input !== pair[1]!.input ||
        pair[0]!.expected !== pair[1]!.expected
      )
        throw new Error("Inconsistent frozen data");
      if (relevant())
        setEvidence({ baseline: pair[0]!, retest: pair[1]!, frozen: row });
    });
  }
  const disabled = busy || !!pending;
  return (
    <div className="space-y-4 rounded-xl border p-4 md:p-6">
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {zh
            ? "操作未确认或来源不符合条件。请核对权限、完整复核、同一基准和新版本标签；不会自动重试写入。"
            : "Operation unconfirmed or sources ineligible. Check permissions, complete review, identical benchmark and distinct version labels. Writes never automatically retry."}
        </p>
      )}
      {pending && (
        <div role="status" className="space-y-2 rounded-md border p-3">
          <p className="text-sm">
            {zh
              ? "保存结果未知，仅可用同一 ID 核对。离开页面前请保留 ID；本页不存浏览器持久化数据。"
              : "Write result unknown. Reconcile the same ID only. Keep this ID before leaving; no browser-persistent storage is used."}
          </p>
          <code className="block text-xs break-all">{pending.id}</code>
          <Button variant="outline" disabled={busy} onClick={reconcile}>
            {zh ? "核对待定比较收据" : "Check pending comparison receipt"}
          </Button>
        </div>
      )}
      <Button variant="outline" disabled={disabled} onClick={loadRuns}>
        {zh ? "加载运行" : "Load runs"}
      </Button>
      <div className="grid gap-3 md:grid-cols-2">
        {(["baseline", "retest"] as const).map((side) => (
          <label key={side} className="min-w-0 space-y-1 text-sm">
            {side === "baseline"
              ? zh
                ? "基准运行"
                : "Baseline run"
              : zh
                ? "复测运行"
                : "Retest run"}
            <select
              aria-label={
                side === "baseline"
                  ? zh
                    ? "基准运行"
                    : "Baseline run"
                  : zh
                    ? "复测运行"
                    : "Retest run"
              }
              className={selectStyle}
              disabled={disabled}
              value={side === "baseline" ? baselineId : retestId}
              onChange={(e) => {
                invalidate();
                if (side === "baseline") setBaselineId(e.target.value);
                else setRetestId(e.target.value);
              }}
            >
              <option value="">{zh ? "选择运行" : "Choose run"}</option>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.component_name} · {run.plan_label} · {run.id.slice(0, 8)}{" "}
                  · {run.status}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <Button
        variant="outline"
        disabled={
          disabled || !baselineId || !retestId || baselineId === retestId
        }
        onClick={verify}
      >
        {zh ? "验证所选汇总" : "Verify selected summaries"}
      </Button>
      {summaries && (
        <div className="bg-muted/40 space-y-1 rounded-md p-3 text-sm">
          <p>
            {summaries[0].component_name}: {summaries[0].plan_label} →{" "}
            {summaries[1].plan_label}
          </p>
          <p>
            {summaries[0].human_pass_rate.numerator} /{" "}
            {summaries[0].human_pass_rate.denominator} →{" "}
            {summaries[1].human_pass_rate.numerator} /{" "}
            {summaries[1].human_pass_rate.denominator}
          </p>
          <p className="text-xs">
            {zh
              ? "仅已验证人工汇总。保存时服务器再次检查基准和版本，未批准验收。"
              : "Verified human summaries only. Saving rechecks benchmark and versions server-side; not acceptance approval."}
          </p>
        </div>
      )}
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={disabled || !summaries}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        {zh
          ? "我确认前后版本及复核口径，保存历史差异；版本标签为人工声明，不是供应方版本认证。"
          : "I confirm the versions and review policy, and archive historical changes. Version labels are human declarations, not supplier-version verification."}
      </label>
      <Button disabled={disabled || !summaries || !confirmed} onClick={create}>
        {zh ? "验证并存档比较" : "Verify & archive comparison"}
      </Button>
      <div className="space-y-3 border-t pt-4">
        <Button variant="outline" disabled={busy} onClick={loadHistory}>
          {zh ? "加载比较历史" : "Load comparison history"}
        </Button>
        <p className="text-muted-foreground text-xs">
          {zh
            ? "显示最近 100 条。旧记录不会因后续复核改写；可填写已保留的 32 位 ID 打开。"
            : "Latest 100 records. Later reviews never rewrite an archive; reopen any retained 32-character ID."}
        </p>
        <select
          aria-label={zh ? "比较历史" : "Comparison history"}
          className={selectStyle}
          value={history.some((row) => row.id === openId) ? openId : ""}
          disabled={busy}
          onChange={(e) => {
            setOpenId(e.target.value);
            setArchive(null);
            setEvidence(null);
          }}
        >
          <option value="">{zh ? "选择历史记录" : "Choose history"}</option>
          {history.map((row) => (
            <option key={row.id} value={row.id}>
              {row.baseline_label} → {row.retest_label} · {row.id.slice(0, 8)}
            </option>
          ))}
        </select>
        <label className="block space-y-1 text-sm">
          {zh ? "比较 ID" : "Comparison ID"}
          <Input
            value={openId}
            disabled={busy}
            maxLength={32}
            onChange={(e) => {
              setOpenId(e.target.value.trim());
              setArchive(null);
              setEvidence(null);
            }}
          />
        </label>
        <Button
          variant="outline"
          disabled={busy || !idPattern.test(openId)}
          onClick={open}
        >
          {zh ? "打开历史比较" : "Open historical comparison"}
        </Button>
      </div>
      {archive && (
        <section
          aria-label={zh ? "已存档差异" : "Archived changes"}
          className="space-y-3 border-t pt-4"
        >
          <h3 className="font-semibold">
            {archive.component_name}: {archive.baseline.plan_label} →{" "}
            {archive.retest.plan_label}
          </h3>
          <p className="text-sm font-medium">
            {zh ? "未批准验收" : "Not approved"}
          </p>
          <p className="text-xl font-semibold">
            {archive.pass_rate_delta.value >= 0 ? "+" : ""}
            {(archive.pass_rate_delta.value * 100).toFixed(2)} pp
          </p>
          <p className="text-muted-foreground text-xs">
            {zh
              ? "人工通过率变化（百分点），分母为全部冻结样本；不是准确率提升认证。"
              : "Human pass-rate change in percentage points, over ALL frozen samples; not certified accuracy improvement."}{" "}
            {archive.pass_rate_delta.numerator} /{" "}
            {archive.pass_rate_delta.denominator}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {Object.entries(labels).map(([key, label]) => (
              <p key={key} className="rounded-md border p-2 text-sm">
                {label}: {archive.transitions[key as RetestTransition]}
              </p>
            ))}
          </div>
          {archive.request_definition_changed && (
            <p className="text-sm">
              {zh
                ? "两次请求定义不同，请复核请求版本；平台不认证供应方实际模型版本。"
                : "Request definitions differ; inspect their versions. The platform does not certify the supplier's actual model version."}
            </p>
          )}
          <label className="block space-y-1 text-sm">
            {zh ? "样本筛选" : "Case filter"}
            <select
              className={selectStyle}
              value={filter}
              onChange={(e) => {
                evidenceEpoch.current++;
                setFilter(e.target.value as typeof filter);
                setEvidence(null);
              }}
            >
              <option value="all">{zh ? "全部样本" : "All samples"}</option>
              {Object.entries(labels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="overflow-x-auto">
            <table
              aria-label={zh ? "冻结样本差异" : "Frozen sample changes"}
              className="w-full text-left text-sm"
            >
              <thead>
                <tr>
                  <th className="p-2">{zh ? "样本" : "Sample"}</th>
                  <th>{zh ? "变化" : "Change"}</th>
                  <th>{zh ? "证据" : "Evidence"}</th>
                </tr>
              </thead>
              <tbody>
                {archive.cases
                  .filter(
                    (row) => filter === "all" || row.transition === filter,
                  )
                  .map((row) => (
                    <tr key={row.ordinal} className="border-t">
                      <td className="max-w-44 p-2 break-all">
                        {row.sample_id}
                      </td>
                      <td>{labels[row.transition]}</td>
                      <td>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={busy}
                          aria-label={
                            (zh ? "打开证据 " : "Open evidence ") +
                            row.sample_id
                          }
                          onClick={() => openEvidence(row)}
                        >
                          {zh ? "查看 Q / A" : "View Q / A"}
                        </Button>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          <details className="text-xs break-all">
            <summary>{zh ? "历史收据" : "Historical receipt"}</summary>
            <p>{archive.id}</p>
            <p>{archive.archive_hash}</p>
            <p>{archive.benchmark_hash}</p>
          </details>
        </section>
      )}
      {evidence && (
        <section
          aria-label={zh ? "前后证据" : "Paired evidence"}
          className="space-y-3 rounded-lg border p-3"
        >
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-semibold">{evidence.frozen.sample_id}</h3>
            <Button
              variant="outline"
              onClick={() => {
                evidenceEpoch.current++;
                setEvidence(null);
              }}
            >
              {zh ? "隐藏证据" : "Hide evidence"}
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">
            {zh
              ? "下方 Q / A 来自显式读取并匹配的冻结证据。当前复核版本可能更新，但不会改写存档结论。"
              : "Q / A below is explicitly opened and matched to frozen evidence. Current review revisions may be newer; archived decisions never change."}
          </p>
          <div>
            <h4>{zh ? "输入 Q" : "Input Q"}</h4>
            <pre className="max-h-64 overflow-auto text-sm break-words whitespace-pre-wrap">
              {evidence.baseline.input}
            </pre>
          </div>
          <div>
            <h4>{zh ? "预期结果" : "Expected result"}</h4>
            <pre className="max-h-64 overflow-auto text-sm break-words whitespace-pre-wrap">
              {evidence.baseline.expected}
            </pre>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {(["baseline", "retest"] as const).map((side) => (
              <div key={side} className="min-w-0 space-y-1">
                <h4>
                  {side === "baseline"
                    ? zh
                      ? "基准输出 A"
                      : "Baseline output A"
                    : zh
                      ? "复测输出 A"
                      : "Retest output A"}
                </h4>
                <p className="text-xs">
                  {zh ? "冻结决定 / 版本" : "Frozen decision / revision"}:{" "}
                  {
                    evidence.frozen[
                      (side + "_decision") as
                        | "baseline_decision"
                        | "retest_decision"
                    ]
                  }{" "}
                  /{" "}
                  {
                    evidence.frozen[
                      (side + "_revision") as
                        | "baseline_revision"
                        | "retest_revision"
                    ]
                  }
                  ; {zh ? "当前版本" : "Current revision"}:{" "}
                  {evidence[side].review_revision}
                </p>
                <pre className="max-h-64 overflow-auto text-sm break-words whitespace-pre-wrap">
                  {evidence[side].output}
                </pre>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
