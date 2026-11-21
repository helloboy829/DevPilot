"use client";

import {
  Check,
  ChevronDown,
  ChevronRight,
  Eye,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import type {
  ProjectList,
  ResultCase,
  ResultPage,
  ResultRun,
} from "@/core/evaluation/result-types";
import {
  createResponseEvidenceAccess,
  getResultCase,
  getResultRun,
  listResultCases,
  listResultProjects,
  listResultRuns,
  readResponseEvidence,
} from "@/core/evaluation/results-api";
import { useI18n } from "@/core/i18n/hooks";

const evidenceLimit = 1_048_576;

export default function EvaluationResultsWorkspace() {
  const { user } = useAuth();
  return <EvaluationResultsWorkspaceContent key={user?.id ?? "anonymous"} />;
}

function EvaluationResultsWorkspaceContent() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const [projects, setProjects] = useState<ProjectList["projects"]>([]);
  const [projectId, setProjectId] = useState("");
  const [runs, setRuns] = useState<ResultPage<ResultRun> | null>(null);
  const [run, setRun] = useState<ResultRun | null>(null);
  const [cases, setCases] = useState<ResultPage<ResultCase> | null>(null);
  const [filters, setFilters] = useState({
    integrity_status: "",
    dispatch_state: "",
    kind: "",
    http_status: "",
    reference_status: "",
  });
  const [selected, setSelected] = useState<ResultCase | null>(null);
  const [detail, setDetail] = useState<ResultCase | null>(null);
  const [responseText, setResponseText] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const requestEpoch = useRef(0);
  const alive = useRef(true);
  const t = (en: string, zhText: string) => (zh ? zhText : en);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      requestEpoch.current += 1;
    };
  }, []);

  function clearCase() {
    requestEpoch.current += 1;
    setSelected(null);
    setDetail(null);
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
      const value = await load();
      if (alive.current && requestEpoch.current === epoch) apply(value);
    } catch (cause) {
      if (alive.current && requestEpoch.current === epoch) {
        setError(
          cause instanceof Error
            ? cause.message
            : t("Request failed", "请求失败"),
        );
        if (name === "cases") {
          setCases(null);
          clearCase();
          setBusy("");
        }
      }
    } finally {
      if (alive.current && requestEpoch.current === epoch) setBusy("");
    }
  }

  const loadProjects = () => {
    clearCase();
    void action("projects", listResultProjects, (result) => {
      setProjects(result.projects);
      setProjectId("");
      setRuns(null);
      setRun(null);
      setCases(null);
    });
  };

  const changeProject = (value: string) => {
    requestEpoch.current += 1;
    setBusy("");
    setProjectId(value);
    setRuns(null);
    setRun(null);
    setCases(null);
    clearCase();
  };

  const loadRuns = () => {
    if (!projectId) return;
    clearCase();
    void action(
      "runs",
      () => listResultRuns(projectId),
      (result) => {
        setRuns(result);
        setRun(null);
        setCases(null);
      },
    );
  };

  const openRun = (item: ResultRun) => {
    clearCase();
    setCases(null);
    setRun(item);
    void action("run", () => getResultRun(projectId, item.run_id), setRun);
  };

  const loadCases = (cursor?: string) => {
    if (!run) return;
    clearCase();
    void action(
      "cases",
      () => listResultCases(projectId, run.run_id, { ...filters, cursor }),
      (result) => {
        setCases(
          cursor && cases
            ? { ...result, items: [...cases.items, ...result.items] }
            : result,
        );
      },
    );
  };

  const openCase = (item: ResultCase) => {
    clearCase();
    setSelected(item);
    void action(
      "detail",
      () => getResultCase(projectId, run!.run_id, item.case_id),
      setDetail,
    );
  };

  const showResponse = async () => {
    if (!run || !selected?.response_evidence?.sha256) return;
    const epoch = ++requestEpoch.current;
    setBusy("evidence");
    setError("");
    setResponseText(null);
    try {
      const grant = await createResponseEvidenceAccess(
        projectId,
        run.run_id,
        selected.ordinal,
        selected.response_evidence.sha256,
      );
      if (!alive.current || requestEpoch.current !== epoch) return;
      const bytes = await readResponseEvidence(
        projectId,
        grant.access_id,
        evidenceLimit,
      );
      try {
        if (alive.current && requestEpoch.current === epoch)
          setResponseText(
            new TextDecoder("utf-8", { fatal: true }).decode(bytes),
          );
      } finally {
        bytes.fill(0);
      }
    } catch (cause) {
      if (alive.current && requestEpoch.current === epoch)
        setError(
          cause instanceof Error
            ? cause.message
            : t("Evidence unavailable", "证据不可用"),
        );
    } finally {
      if (alive.current && requestEpoch.current === epoch) setBusy("");
    }
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {t("Effectiveness results", "效果测试结果")}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody className="overflow-y-auto">
        <main className="mx-auto w-full max-w-7xl space-y-5 p-4 md:p-6">
          <section
            aria-label={t("Project and runs", "项目与运行")}
            className="flex flex-wrap items-end gap-3 border-b pb-4"
          >
            <Button onClick={loadProjects} disabled={!!busy}>
              {busy === "projects" ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <RefreshCw className="size-4" />
              )}
              {t("Load projects", "加载项目")}
            </Button>
            <label className="grid min-w-56 gap-1 text-sm">
              {t("Project", "项目")}
              <select
                className="bg-background h-9 rounded border px-2"
                value={projectId}
                onChange={(e) => changeProject(e.target.value)}
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
              onClick={loadRuns}
              disabled={!projectId || !!busy}
            >
              {t("Load runs", "加载运行")}
            </Button>
          </section>

          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}

          {runs && (
            <section
              aria-label={t("Run results", "运行结果")}
              className="space-y-3"
            >
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="font-semibold">{t("Runs", "运行列表")}</h2>
                <span className="text-muted-foreground text-sm">
                  {runs.matched_total} / {runs.total}
                </span>
              </div>
              {runs.items.length === 0 && (
                <p className="text-muted-foreground text-sm">
                  {t("No matching runs", "没有匹配的运行")}
                </p>
              )}
              <ul className="divide-y border-y">
                {runs.items.map((item) => (
                  <li key={item.run_id}>
                    <button
                      className="hover:bg-muted/50 flex w-full flex-wrap items-center justify-between gap-3 py-3 text-left"
                      onClick={() => openRun(item)}
                    >
                      <span className="flex items-center gap-2">
                        <ChevronRight className="size-4" />
                        {item.run_id}
                      </span>
                      <span className="text-sm">
                        {new Date(item.started_at_ms).toLocaleString(locale)} ·{" "}
                        {item.status} · {item.verdict} · {item.total}{" "}
                        {t("cases", "条")}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              {runs.next_cursor && (
                <Button
                  variant="outline"
                  disabled={!!busy}
                  onClick={() =>
                    void action(
                      "runs-more",
                      () =>
                        listResultRuns(projectId, {
                          cursor: runs.next_cursor!,
                        }),
                      (next) =>
                        setRuns({
                          ...next,
                          items: [...runs.items, ...next.items],
                        }),
                    )
                  }
                >
                  {t("Load more runs", "加载更多运行")}
                </Button>
              )}
            </section>
          )}

          {run && (
            <section
              aria-label={t("Selected run", "运行摘要")}
              className="space-y-3 border-t pt-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h2 className="font-semibold">
                    {t("Run summary", "运行摘要")}
                  </h2>
                  <p className="text-muted-foreground text-sm">
                    {run.run_id} · {run.status} · {run.verdict}
                  </p>
                </div>
                <Button
                  variant="outline"
                  onClick={() => {
                    setRun(null);
                    setCases(null);
                    clearCase();
                  }}
                >
                  {t("Close run", "关闭运行")}
                </Button>
              </div>
              <dl className="grid grid-cols-2 gap-x-5 gap-y-2 text-sm md:grid-cols-4">
                <div>
                  <dt className="text-muted-foreground">
                    {t("Frozen cases", "冻结样本")}
                  </dt>
                  <dd>{run.total}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">
                    {t("Requests", "请求数")}
                  </dt>
                  <dd>{run.request_count}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">
                    {t("Concurrency", "并发数")}
                  </dt>
                  <dd>{run.concurrency}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">
                    {t("Technical states", "技术状态")}
                  </dt>
                  <dd>
                    {Object.entries(run.technical_counts ?? {})
                      .map(([key, count]) => `${key}: ${count}`)
                      .join(" · ") || "—"}
                  </dd>
                </div>
                <div className="col-span-full">
                  <dt className="text-muted-foreground">
                    {t("Blockers", "阻塞项")}
                  </dt>
                  <dd>{run.blockers?.join(" · ") || t("None", "无")}</dd>
                </div>
              </dl>
              <div className="flex flex-wrap gap-2">
                {(
                  [
                    "integrity_status",
                    "dispatch_state",
                    "kind",
                    "http_status",
                    "reference_status",
                  ] as const
                ).map((key) => (
                  <label key={key} className="grid gap-1 text-xs">
                    {key.replaceAll("_", " ")}
                    <select
                      className="bg-background h-9 min-w-32 rounded border px-2 text-sm"
                      value={filters[key]}
                      onChange={(e) => {
                        setFilters({ ...filters, [key]: e.target.value });
                        requestEpoch.current += 1;
                        setBusy("");
                        setCases(null);
                        clearCase();
                      }}
                    >
                      <option value="">{t("Any", "全部")}</option>
                      {(key === "integrity_status"
                        ? ["complete", "missing_dispatch", "sample_mismatch"]
                        : key === "dispatch_state"
                          ? [
                              "pending",
                              "dispatched",
                              "succeeded",
                              "failed",
                              "delivery_unknown",
                              "not_dispatched",
                            ]
                          : key === "kind"
                            ? ["http", "error", "timeout"]
                            : key === "http_status"
                              ? [
                                  "200",
                                  "400",
                                  "401",
                                  "403",
                                  "404",
                                  "429",
                                  "500",
                                  "502",
                                  "503",
                                ]
                              : ["provided", "absent"]
                      ).map((value) => (
                        <option key={value}>{value}</option>
                      ))}
                    </select>
                  </label>
                ))}
                <Button
                  className="self-end"
                  onClick={() => loadCases()}
                  disabled={!!busy}
                >
                  <Check className="size-4" />
                  {t("Load cases", "加载样本")}
                </Button>
              </div>
              {cases && (
                <>
                  <div className="flex justify-between text-sm">
                    <span>
                      {t("Matched / frozen", "匹配 / 冻结")}:{" "}
                      {cases.matched_total} / {cases.total}
                    </span>
                    <span>
                      {t("Page", "本页")}: {cases.items.length}
                    </span>
                  </div>
                  <div className="overflow-x-auto border-y">
                    <table className="w-full min-w-[760px] text-left text-sm">
                      <caption className="sr-only">
                        {t("Effectiveness case results", "效果测试逐条结果")}
                      </caption>
                      <thead>
                        <tr className="text-muted-foreground border-b">
                          <th className="p-2">#</th>
                          <th className="p-2">ID</th>
                          <th className="p-2">{t("Technical", "技术状态")}</th>
                          <th className="p-2">HTTP</th>
                          <th className="p-2">{t("Latency", "延迟")}</th>
                          <th className="p-2">{t("Reference", "参考答案")}</th>
                          <th className="p-2">
                            {t("Response evidence", "响应证据")}
                          </th>
                          <th className="p-2" />
                        </tr>
                      </thead>
                      <tbody>
                        {cases.items.map((item) => (
                          <tr key={item.case_id} className="border-b align-top">
                            <td className="p-2">{item.ordinal}</td>
                            <td
                              className="max-w-44 truncate p-2"
                              title={item.case_id}
                            >
                              {item.case_id}
                            </td>
                            <td className="p-2">
                              {item.integrity_status} ·{" "}
                              {item.dispatch_state ?? "—"}
                            </td>
                            <td className="p-2">{item.http_status ?? "—"}</td>
                            <td className="p-2">
                              {item.latency_ms == null
                                ? "—"
                                : `${item.latency_ms} ms`}
                            </td>
                            <td className="p-2">{item.reference_status}</td>
                            <td className="p-2">
                              {item.response_evidence?.status ??
                                t("Unavailable", "不可用")}
                            </td>
                            <td className="p-2">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => openCase(item)}
                              >
                                <ChevronDown className="size-4" />
                                {t("Details", "详情")}
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="flex gap-2">
                    {cases.next_cursor && (
                      <Button
                        variant="outline"
                        disabled={!!busy}
                        onClick={() => loadCases(cases.next_cursor!)}
                      >
                        {t("Next page", "下一页")}
                      </Button>
                    )}
                  </div>
                </>
              )}
            </section>
          )}

          {selected && (
            <section
              aria-label={t("Case detail", "样本详情")}
              className="space-y-3 border-t pt-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="font-semibold">
                    {t("Case details", "样本详情")}: {selected.case_id}
                  </h2>
                  <p className="text-muted-foreground text-sm">
                    {t(
                      "Only metadata is loaded until an explicit evidence action.",
                      "普通详情仅含元数据；正文需要单独明确读取。",
                    )}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("Close details", "关闭详情")}
                  title={t("Close details", "关闭详情")}
                  onClick={clearCase}
                >
                  <X className="size-4" />
                </Button>
              </div>
              {busy === "detail" ? (
                <p aria-live="polite">
                  {t("Loading details…", "正在加载详情…")}
                </p>
              ) : (
                detail && (
                  <dl className="grid gap-2 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-muted-foreground">
                        {t("Dispatch", "派发")}
                      </dt>
                      <dd>
                        {detail.dispatch_state ?? "—"} · {detail.kind ?? "—"} ·{" "}
                        {detail.http_status ?? "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("Measured latency", "实测延迟")}
                      </dt>
                      <dd>
                        {detail.latency_ms == null
                          ? "—"
                          : `${detail.latency_ms} ms`}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("Parsed output available", "解析输出")}
                      </dt>
                      <dd>
                        {detail.output_evidence?.available
                          ? t(
                              "Available as separate evidence",
                              "存在独立证据，当前未加载",
                            )
                          : t("Unavailable", "不可用")}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">
                        {t("Captured response", "原生响应")}
                      </dt>
                      <dd>
                        {detail.response_evidence?.status ??
                          t("Unavailable", "不可用")}{" "}
                        · {detail.response_evidence?.captured_bytes ?? "—"} B ·{" "}
                        {detail.response_evidence?.content_type ?? "—"}
                      </dd>
                    </div>
                  </dl>
                )
              )}
              {detail?.response_evidence?.sha256 &&
                detail.response_evidence.status === "complete" && (
                  <Button onClick={showResponse} disabled={!!busy}>
                    <Eye className="size-4" />
                    {busy === "evidence"
                      ? t("Loading response…", "正在读取响应…")
                      : t(
                          "Authorize and view captured response",
                          "授权并查看原生响应",
                        )}
                  </Button>
                )}
              {responseText !== null && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="font-medium">
                      {t(
                        "Captured response (plain text)",
                        "原生响应（纯文本）",
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
        </main>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
