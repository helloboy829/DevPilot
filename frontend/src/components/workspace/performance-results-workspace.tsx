"use client";

import {
  ChevronDown,
  ChevronRight,
  Eye,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import {
  createPerformanceEvidenceAccess,
  getPerformanceRun,
  getPerformanceMetrics,
  listPerformanceDispatches,
  listPerformanceRuns,
  readPerformanceEvidence,
  type PerformanceDispatch,
  type PerformanceRun,
  type PerformanceMetricsEnvelope,
} from "@/core/evaluation/performance-results-api";
import type { ProjectList } from "@/core/evaluation/result-types";
import { listResultProjects } from "@/core/evaluation/results-api";
import { useI18n } from "@/core/i18n/hooks";

const evidenceLimit = 1_048_576;
const dispatchPageSize = 100;

export default function PerformanceResultsWorkspace() {
  const { user } = useAuth();
  return <PerformanceResultsContent key={user?.id ?? "anonymous"} />;
}

function PerformanceResultsContent() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const t = (en: string, zhText: string) => (zh ? zhText : en);
  const [projects, setProjects] = useState<ProjectList["projects"]>([]);
  const [projectId, setProjectId] = useState("");
  const [runs, setRuns] = useState<PerformanceRun[]>([]);
  const [runCursor, setRunCursor] = useState<string | null>(null);
  const [run, setRun] = useState<PerformanceRun | null>(null);
  const [metricsResult, setMetricsResult] =
    useState<PerformanceMetricsEnvelope | null>(null);
  const [dispatches, setDispatches] = useState<PerformanceDispatch[]>([]);
  const [dispatchOffset, setDispatchOffset] = useState(0);
  const [phaseFilter, setPhaseFilter] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [sampleFilter, setSampleFilter] = useState("");
  const [selected, setSelected] = useState<PerformanceDispatch | null>(null);
  const [responseText, setResponseText] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const requestEpoch = useRef(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      requestEpoch.current += 1;
    };
  }, []);

  function clearDetail() {
    if (busy === "evidence") {
      requestEpoch.current += 1;
      setBusy("");
    }
    setSelected(null);
    setResponseText(null);
  }

  async function action<T>(
    name: string,
    load: () => Promise<T>,
    apply: (value: T) => void,
  ) {
    const epoch = ++requestEpoch.current;
    setBusy(name);
    setError("");
    try {
      const result = await load();
      if (alive.current && requestEpoch.current === epoch) apply(result);
    } catch (cause) {
      if (alive.current && requestEpoch.current === epoch) {
        setError(
          cause instanceof Error
            ? cause.message
            : t("Request failed", "请求失败"),
        );
        if (name === "dispatches") {
          setDispatches([]);
          setDispatchOffset(0);
          clearDetail();
        }
      }
    } finally {
      if (alive.current && requestEpoch.current === epoch) setBusy("");
    }
  }

  const loadProjects = () => {
    clearDetail();
    void action("projects", listResultProjects, (result) => {
      setProjects(result.projects);
      setProjectId("");
      setRuns([]);
      setRun(null);
      setMetricsResult(null);
      setDispatches([]);
    });
  };

  const changeProject = (value: string) => {
    requestEpoch.current += 1;
    setBusy("");
    setProjectId(value);
    setRuns([]);
    setRunCursor(null);
    setRun(null);
    setDispatches([]);
    setDispatchOffset(0);
    clearDetail();
  };

  const loadRuns = (cursor?: string) => {
    if (!projectId) return;
    clearDetail();
    void action(
      "runs",
      () => listPerformanceRuns(projectId, { cursor }),
      (result) => {
        setRuns((current) =>
          cursor ? [...current, ...result.items] : result.items,
        );
        setRunCursor(result.next_cursor);
        setRun(null);
        setDispatches([]);
      },
    );
  };

  const openRun = (item: PerformanceRun) => {
    clearDetail();
    setRun(item);
    setMetricsResult(null);
    setDispatches([]);
    setDispatchOffset(0);
    void action(
      "run",
      async () => {
        const [runResult, metricResult] = await Promise.all([
          getPerformanceRun(projectId, item.id),
          getPerformanceMetrics(projectId, item.id),
        ]);
        return { runResult, metricResult };
      },
      ({ runResult, metricResult }) => {
        setRun(runResult);
        setMetricsResult(metricResult);
      },
    );
  };

  const loadDispatches = (offset = 0) => {
    if (!run) return;
    clearDetail();
    void action(
      "dispatches",
      () =>
        listPerformanceDispatches(projectId, run.id, {
          offset,
          limit: dispatchPageSize,
        }),
      (result) => {
        setDispatches((current) =>
          offset ? [...current, ...result.dispatches] : result.dispatches,
        );
        setDispatchOffset(offset + result.dispatches.length);
      },
    );
  };

  const visibleDispatches = useMemo(
    () =>
      dispatches.filter(
        (item) =>
          (!phaseFilter || item.phase === phaseFilter) &&
          (!stateFilter || item.state === stateFilter) &&
          (!sampleFilter ||
            item.sample_id
              .toLowerCase()
              .includes(sampleFilter.trim().toLowerCase())),
      ),
    [dispatches, phaseFilter, sampleFilter, stateFilter],
  );

  const showResponse = async () => {
    if (
      !run ||
      !selected?.response_sha256 ||
      selected.response_capture_status !== "complete"
    )
      return;
    const epoch = ++requestEpoch.current;
    setBusy("evidence");
    setError("");
    setResponseText(null);
    try {
      const grant = await createPerformanceEvidenceAccess(
        projectId,
        run.id,
        selected.ordinal,
        selected.response_sha256,
      );
      const bytes = await readPerformanceEvidence(
        projectId,
        grant.access_id,
        evidenceLimit,
      );
      if (alive.current && requestEpoch.current === epoch)
        setResponseText(new TextDecoder("utf-8").decode(bytes));
    } catch (cause) {
      if (alive.current && requestEpoch.current === epoch)
        setError(
          cause instanceof Error
            ? cause.message
            : t("Evidence is unavailable", "证据不可用"),
        );
    } finally {
      if (alive.current && requestEpoch.current === epoch) setBusy("");
    }
  };

  const metric = (label: string, value: string) => (
    <div className="min-w-0 border-l-2 pl-3">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="mt-1 font-medium break-words tabular-nums">{value}</dd>
    </div>
  );
  const rate = (value: number | null | undefined) =>
    value == null ? "—" : `${Number(value.toFixed(3))} req/s`;
  const latency = (value: number | null | undefined) =>
    value == null ? "—" : `${Number(value.toFixed(2))} ms`;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold">
            {t("Performance results", "性能结果")}
          </h1>
          {busy && (
            <LoaderCircle
              className="text-muted-foreground size-4 animate-spin"
              aria-label={t("Loading", "加载中")}
            />
          )}
        </div>
      </WorkspaceHeader>
      <WorkspaceBody className="overflow-y-auto">
        <main className="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-8">
          <section
            className="space-y-3 border-b pb-5"
            aria-label={t("Project selection", "项目选择")}
          >
            <div className="flex flex-wrap items-end gap-3">
              <label className="grid min-w-56 gap-1 text-sm">
                <span>{t("Project", "项目")}</span>
                <select
                  className="bg-background h-9 rounded border px-2"
                  aria-label={t("Project", "项目")}
                  value={projectId}
                  onChange={(event) => changeProject(event.target.value)}
                >
                  <option value="">{t("Select a project", "选择项目")}</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                variant="outline"
                onClick={loadProjects}
                disabled={!!busy}
              >
                <RefreshCw className="size-4" />
                {t("Load projects", "加载项目")}
              </Button>
              <Button
                onClick={() => loadRuns()}
                disabled={!projectId || !!busy}
              >
                {t("Load performance runs", "加载性能运行")}
              </Button>
            </div>
            {error && (
              <p role="alert" className="text-destructive text-sm">
                {error}
              </p>
            )}
          </section>

          {runs.length > 0 && (
            <section
              className="space-y-3"
              aria-labelledby="performance-runs-heading"
            >
              <div className="flex items-center justify-between gap-3">
                <h2 id="performance-runs-heading" className="font-semibold">
                  {t("Runs", "运行记录")}
                </h2>
                {runCursor && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => loadRuns(runCursor)}
                    disabled={!!busy}
                  >
                    {t("Load more runs", "加载更多运行")}
                  </Button>
                )}
              </div>
              <div className="divide-y border-y">
                {runs.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`hover:bg-muted/40 flex w-full items-center justify-between gap-4 py-3 text-left ${run?.id === item.id ? "bg-muted/50" : ""}`}
                    onClick={() => openRun(item)}
                    disabled={!!busy}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <ChevronRight className="size-4 shrink-0" />
                      <span className="truncate font-mono text-sm">
                        {item.id}
                      </span>
                    </span>
                    <span className="text-muted-foreground flex shrink-0 gap-4 text-xs">
                      <span>{item.status}</span>
                      <span>
                        {item.population_count} {t("requests", "请求")}
                      </span>
                      <time>{new Date(item.created_at).toLocaleString()}</time>
                    </span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {run && (
            <>
              <section
                className="space-y-4 border-y py-4"
                aria-labelledby="performance-summary-heading"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2
                      id="performance-summary-heading"
                      className="font-semibold"
                    >
                      {t("Run summary", "运行摘要")}
                    </h2>
                    <p className="text-muted-foreground mt-1 font-mono text-xs">
                      {run.id} · {run.status} ·{" "}
                      {metricsResult?.metrics?.quantile_method ??
                        t("Metrics unavailable", "指标不可用")}
                    </p>
                    <p className="text-muted-foreground mt-1 text-xs">
                      {t(
                        "Metrics applicability",
                        "\u6307\u6807\u9002\u7528\u6027",
                      )}
                      :{" "}
                      {metricsResult?.applicability ??
                        t("loading", "\u52a0\u8f7d\u4e2d")}
                      {metricsResult?.revision
                        ? ` | ${metricsResult.revision}`
                        : ""}
                    </p>
                  </div>
                  <p className="text-muted-foreground max-w-lg text-xs">
                    {t(
                      "Ledger-only view. It does not imply that requests were sent or that this run completed successfully.",
                      "仅展示持久账本；不代表请求已发送，也不代表本次运行成功完成。",
                    )}
                  </p>
                </div>
                {metricsResult?.metrics ? (
                  <dl className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-6">
                    {metric(
                      t("Attempt QPS", "尝试 QPS"),
                      rate(metricsResult.metrics.attempt_qps),
                    )}
                    {metric(
                      t("Success QPS", "成功 QPS"),
                      rate(metricsResult.metrics.success_qps),
                    )}
                    {metric(
                      t("Succeeded", "成功"),
                      String(metricsResult.metrics.state_counts.succeeded ?? 0),
                    )}
                    {metric(
                      t("Failed", "失败"),
                      String(metricsResult.metrics.state_counts.failed ?? 0),
                    )}
                    {metric(
                      t("Unknown", "未知"),
                      String(metricsResult.metrics.state_counts.unknown ?? 0),
                    )}
                    {metric(
                      t("Not dispatched", "未派发"),
                      String(
                        metricsResult.metrics.state_counts.not_dispatched ?? 0,
                      ),
                    )}
                    {metric(
                      t("p50 / p90 / p99", "成功 p50 / p90 / p99"),
                      `${latency(metricsResult.metrics.successful_latency_ms.p50)} / ${latency(metricsResult.metrics.successful_latency_ms.p90)} / ${latency(metricsResult.metrics.successful_latency_ms.p99)}`,
                    )}
                    {metric(
                      t(
                        "Failed latency p50 / p90 / p99",
                        "失败 p50 / p90 / p99",
                      ),
                      `${latency(metricsResult.metrics.failed_latency_ms.p50)} / ${latency(metricsResult.metrics.failed_latency_ms.p90)} / ${latency(metricsResult.metrics.failed_latency_ms.p99)}`,
                    )}
                    {metric(
                      t(
                        "Failed latency samples / max",
                        "失败延迟样本 / 最大值",
                      ),
                      `${metricsResult.metrics.failed_latency_ms.n} / ${latency(metricsResult.metrics.failed_latency_ms.max)}`,
                    )}
                    {metric(
                      t("Rate applicability", "速率适用性"),
                      metricsResult.metrics.rate_applicability,
                    )}
                    {metric(
                      t("Output tokens", "输出 token"),
                      metricsResult.metrics.output_token_count == null
                        ? "—"
                        : String(metricsResult.metrics.output_token_count),
                    )}
                    {metric(
                      t("Token throughput", "Token 吞吐"),
                      metricsResult.metrics.output_token_throughput == null
                        ? "—"
                        : `${Number(metricsResult.metrics.output_token_throughput.toFixed(3))} tok/s`,
                    )}
                    {metric(
                      t("Token applicability", "Token 适用性"),
                      metricsResult.metrics.token_applicability,
                    )}
                    {metric(
                      t("Censored", "删失请求"),
                      String(metricsResult.metrics.censored_count),
                    )}
                    {metric(
                      t("Successful latency applicability", "成功延迟适用性"),
                      metricsResult.metrics.successful_latency_ms
                        .p99_applicability,
                    )}
                  </dl>
                ) : (
                  <p className="text-muted-foreground text-sm">
                    {t(
                      "No summary metrics are available for this run.",
                      "此运行没有可用的汇总指标。",
                    )}
                  </p>
                )}
              </section>

              <section
                className="space-y-3"
                aria-labelledby="dispatches-heading"
              >
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <h2 id="dispatches-heading" className="font-semibold">
                      {t("Request ledger", "请求账本")}
                    </h2>
                    <p className="text-muted-foreground mt-1 text-xs">
                      {t(
                        "Filters apply to loaded pages. Unknown and not-dispatched rows are retained.",
                        "筛选仅作用于已加载页面；未知和未派发行会保留。",
                      )}
                    </p>
                  </div>
                  <Button onClick={() => loadDispatches(0)} disabled={!!busy}>
                    {t("Load dispatches", "加载派发记录")}
                  </Button>
                </div>
                <div className="flex flex-wrap gap-3">
                  <label className="grid gap-1 text-xs">
                    <span>{t("Phase", "阶段")}</span>
                    <select
                      className="bg-background h-9 min-w-36 rounded border px-2"
                      aria-label={t("Phase filter", "阶段筛选")}
                      value={phaseFilter}
                      onChange={(event) => setPhaseFilter(event.target.value)}
                    >
                      <option value="">{t("All phases", "全部阶段")}</option>
                      <option value="warmup">warmup</option>
                      <option value="measurement">measurement</option>
                    </select>
                  </label>
                  <label className="grid gap-1 text-xs">
                    <span>{t("State", "状态")}</span>
                    <select
                      className="bg-background h-9 min-w-36 rounded border px-2"
                      aria-label={t("State filter", "状态筛选")}
                      value={stateFilter}
                      onChange={(event) => setStateFilter(event.target.value)}
                    >
                      <option value="">{t("All states", "全部状态")}</option>
                      {[...new Set(dispatches.map((item) => item.state))]
                        .sort()
                        .map((state) => (
                          <option key={state}>{state}</option>
                        ))}
                    </select>
                  </label>
                  <label className="grid gap-1 text-xs">
                    <span>{t("Sample ID", "样本 ID")}</span>
                    <input
                      className="bg-background h-9 min-w-48 rounded border px-2"
                      aria-label={t("Sample filter", "样本筛选")}
                      value={sampleFilter}
                      onChange={(event) => setSampleFilter(event.target.value)}
                    />
                  </label>
                </div>
                {dispatches.length > 0 && (
                  <div className="overflow-x-auto border-y">
                    <table className="w-full min-w-[760px] text-left text-sm">
                      <thead className="text-muted-foreground border-b text-xs">
                        <tr>
                          <th className="py-2 pr-3">#</th>
                          <th className="py-2 pr-3">{t("Sample", "样本")}</th>
                          <th className="py-2 pr-3">{t("Phase", "阶段")}</th>
                          <th className="py-2 pr-3">{t("State", "状态")}</th>
                          <th className="py-2 pr-3">{t("Latency", "延迟")}</th>
                          <th className="py-2 pr-3">HTTP</th>
                          <th className="py-2">{t("Details", "详情")}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {visibleDispatches.map((item) => (
                          <tr key={item.id} className="align-top">
                            <td className="py-2 pr-3 tabular-nums">
                              {item.ordinal}
                            </td>
                            <td
                              className="max-w-64 truncate py-2 pr-3 font-mono text-xs"
                              title={item.sample_id}
                            >
                              {item.sample_id}
                            </td>
                            <td className="py-2 pr-3">{item.phase}</td>
                            <td className="py-2 pr-3">{item.state}</td>
                            <td className="py-2 pr-3 tabular-nums">
                              {latency(item.elapsed_ms)}
                            </td>
                            <td className="py-2 pr-3 tabular-nums">
                              {item.response_status ?? "—"}
                            </td>
                            <td className="py-2">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => {
                                  clearDetail();
                                  setSelected(item);
                                }}
                                disabled={!!busy}
                              >
                                <ChevronDown className="size-4" />
                                {t("Details", "详情")}
                              </Button>
                            </td>
                          </tr>
                        ))}
                        {visibleDispatches.length === 0 && (
                          <tr>
                            <td
                              colSpan={7}
                              className="text-muted-foreground py-6 text-center"
                            >
                              {t(
                                "No loaded requests match these filters.",
                                "已加载记录中没有符合筛选条件的请求。",
                              )}
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
                {dispatches.length > 0 &&
                  dispatches.length === dispatchPageSize && (
                    <div className="flex justify-center">
                      <Button
                        variant="outline"
                        onClick={() => loadDispatches(dispatchOffset)}
                        disabled={!!busy}
                      >
                        {t("Load next page", "加载下一页")}
                      </Button>
                    </div>
                  )}
              </section>

              {selected && (
                <section
                  className="space-y-4 border-t pt-4"
                  aria-labelledby="dispatch-detail-heading"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2
                        id="dispatch-detail-heading"
                        className="font-semibold"
                      >
                        {t("Dispatch details", "派发详情")} · #
                        {selected.ordinal}
                      </h2>
                      <p className="text-muted-foreground mt-1 text-xs">
                        {t(
                          "Metadata only until you explicitly authorize response access.",
                          "默认仅展示元数据；响应正文需单独明确授权读取。",
                        )}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("Close details", "关闭详情")}
                      title={t("Close details", "关闭详情")}
                      onClick={clearDetail}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                  <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
                    {[
                      [t("Sample", "样本"), selected.sample_id],
                      [t("Phase", "阶段"), selected.phase],
                      [t("State", "状态"), selected.state],
                      [
                        t("Iteration", "轮次"),
                        String(selected.iteration_index),
                      ],
                      [t("Profile step", "负载档位"), selected.profile_step_id],
                      [
                        t("Request bytes", "请求字节"),
                        String(selected.request_bytes ?? "—"),
                      ],
                      [
                        t("Request SHA-256", "请求 SHA-256"),
                        selected.request_sha256 ?? "—",
                      ],
                      [
                        t("Response capture", "响应留存状态"),
                        selected.response_capture_status ?? "—",
                      ],
                      [
                        t("Response SHA-256", "响应 SHA-256"),
                        selected.response_sha256 ?? "—",
                      ],
                      [
                        t("Captured response bytes", "留存响应字节"),
                        String(selected.captured_response_bytes ?? "—"),
                      ],
                      [
                        t("Token source", "Token 来源"),
                        selected.token_source ?? "—",
                      ],
                    ].map(([label, value]) => (
                      <div key={label} className="min-w-0">
                        <dt className="text-muted-foreground text-xs">
                          {label}
                        </dt>
                        <dd className="mt-1 font-mono text-xs break-all">
                          {value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  {selected.response_sha256 &&
                    selected.response_capture_status === "complete" && (
                      <Button onClick={showResponse} disabled={!!busy}>
                        <Eye className="size-4" />
                        {busy === "evidence"
                          ? t("Reading response…", "正在读取响应…")
                          : t(
                              "Authorize and view captured response",
                              "授权并查看已留存响应",
                            )}
                      </Button>
                    )}
                  {responseText !== null && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <h3 className="font-medium">
                          {t(
                            "Captured response (plain text)",
                            "已留存响应（纯文本）",
                          )}
                        </h3>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={t("Clear response", "清除响应")}
                          onClick={() => setResponseText(null)}
                        >
                          <X className="size-4" />
                        </Button>
                      </div>
                      <pre className="max-h-[32rem] overflow-auto border p-3 text-xs break-words whitespace-pre-wrap">
                        {responseText}
                      </pre>
                    </div>
                  )}
                </section>
              )}
            </>
          )}
        </main>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
