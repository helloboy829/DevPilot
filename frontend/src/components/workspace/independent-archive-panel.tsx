"use client";
import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EvaluationCriteriaView } from "@/components/workspace/evaluation-criteria-view";
import { evaluationApi } from "@/core/evaluation/api";
import {
  assessmentIdValid,
  parseAssessmentArchive,
  parseAssessmentHistory,
  type AssessmentArchive,
  type AssessmentMetadata,
} from "@/core/evaluation/assessment-policy";
import {
  archivedSource,
  independentPendingKey,
  parseIndependentArchive,
  parseIndependentHistory,
  parseIndependentReceipt,
  parseIndependentTemplates,
  sourceReference,
  type ArchiveKind,
  type IndependentArchive,
  type IndependentMetadata,
  type IndependentReport,
  type IndependentSource,
  type IndependentTemplate,
  type PendingIndependentArchive,
  type PendingIndependentArchives,
} from "@/core/evaluation/independent-archive-policy";
const selectClass =
  "bg-background w-full min-w-0 rounded-md border p-2 text-sm";
const identifier = z.string().min(1).max(160);
const projectsSchema = z.object({
  projects: z
    .array(z.object({ id: identifier, name: z.string().min(1).max(1000) }))
    .max(1000),
});
const runsSchema = z.object({
  runs: z
    .array(
      z.object({
        id: identifier,
        component_name: z.string().min(1).max(1000),
        plan_label: z.string().min(1).max(160),
      }),
    )
    .max(1000),
});
type Run = z.infer<typeof runsSchema>["runs"][number];
type Operation = (
  fn: (current: () => boolean) => Promise<void>,
) => Promise<void>;
/** Explicit reads only. Pending identifiers live synchronously in page memory across scope changes. */
export function IndependentArchivePanel({
  kind,
  zh,
}: {
  kind: ArchiveKind;
  zh: boolean;
}) {
  const [projects, setProjects] = useState<
      z.infer<typeof projectsSchema>["projects"]
    >([]),
    [projectId, setProjectId] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  const pending = useRef<PendingIndependentArchives>(new Map()),
    writeLock = useRef(false),
    lock = useRef(false),
    epoch = useRef(0);
  useEffect(() => {
    const ref = epoch;
    return () => {
      ref.current++;
    };
  }, []);
  async function loadProjects() {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(false);
    const token = epoch.current;
    try {
      const result = projectsSchema.parse(
        await evaluationApi<unknown>("evaluation/projects"),
      );
      if (token === epoch.current) setProjects(result.projects);
    } catch {
      if (token === epoch.current) setError(true);
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  return (
    <section
      aria-label={
        zh
          ? kind === "report"
            ? "独立历史报告档案"
            : "独立历史复测档案"
          : kind === "report"
            ? "Independent historical report archives"
            : "Independent historical retest archives"
      }
      className="mb-6 min-w-0 space-y-4 rounded-xl border p-4 md:p-6 [&_button]:h-auto [&_button]:max-w-full [&_button]:whitespace-normal"
    >
      <h2 className="text-lg font-semibold">
        {zh
          ? kind === "report"
            ? "独立评估 → 历史报告草稿"
            : "独立评估 → 同基准历史复测"
          : kind === "report"
            ? "Independent assessments → historical report drafts"
            : "Independent assessments → historical same-benchmark retests"}
      </h2>
      <p className="text-muted-foreground text-sm">
        {zh
          ? "显式选择已打开的历史独立评估 ID、修订和哈希，不默认最新，不混入 owner 自复核。分母为全部冻结样本；完整复核、阈值达标均不等于正式批准。后续任务重开不改写旧档案。"
          : "Explicitly select opened historical independent assessment IDs, revisions and hashes. No latest-state default or owner-vote substitution. ALL frozen samples are the denominator. Complete review and met thresholds are not formal approval. Later task reopens never rewrite archives."}
      </p>
      <Button
        variant="outline"
        disabled={busy}
        onClick={() => void loadProjects()}
      >
        {zh ? "加载独立档案项目" : "Load independent archive projects"}
      </Button>
      <label className="block space-y-1 text-sm">
        {zh ? "独立档案项目" : "Independent archive project"}
        <select
          aria-label={zh ? "独立档案项目" : "Independent archive project"}
          className={selectClass}
          value={projectId}
          disabled={busy}
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
      {error && (
        <p role="alert">
          {zh
            ? "项目读取失败，请核对权限后手动刷新。"
            : "Project read failed; check permissions before manually refreshing."}
        </p>
      )}
      {projectId && (
        <IndependentArchiveWorkspace
          key={JSON.stringify([projectId, kind, zh])}
          projectId={projectId}
          kind={kind}
          zh={zh}
          pendingArchives={pending.current}
          writeLock={writeLock}
        />
      )}
    </section>
  );
}
export function IndependentArchiveWorkspace({
  projectId,
  kind,
  zh,
  pendingArchives,
  writeLock,
}: {
  projectId: string;
  kind: ArchiveKind;
  zh: boolean;
  pendingArchives: PendingIndependentArchives;
  writeLock: MutableRefObject<boolean>;
}) {
  const key = independentPendingKey(projectId, kind),
    base = "evaluation/projects/" + encodeURIComponent(projectId),
    namespace =
      kind === "report"
        ? "independent-report-archives"
        : "independent-retest-archives";
  const [loadRevision, setLoadRevision] = useState(0),
    [runs, setRuns] = useState<Run[]>([]),
    [templates, setTemplates] = useState<IndependentTemplate[]>([]),
    [history, setHistory] = useState<IndependentMetadata[]>([]),
    [staged, setStaged] = useState<IndependentSource[]>([]),
    [baseline, setBaseline] = useState<IndependentSource | null>(null),
    [retest, setRetest] = useState<IndependentSource | null>(null),
    [title, setTitle] = useState(""),
    [templateId, setTemplateId] = useState(""),
    [parent, setParent] = useState<IndependentReport | null>(null),
    [opened, setOpened] = useState<IndependentArchive | null>(null),
    [lookup, setLookup] = useState(""),
    [pending, setPending] = useState<PendingIndependentArchive | null>(
      () => pendingArchives.get(key) ?? null,
    ),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  const lock = useRef(false),
    epoch = useRef(0);
  useEffect(() => {
    const ref = epoch;
    return () => {
      ref.current++;
    };
  }, []);
  const locked = busy || !!pending;
  const revoke = () => setConfirmed(false);
  async function operation(fn: (current: () => boolean) => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    const current = () => token === epoch.current;
    setBusy(true);
    setError(false);
    revoke();
    try {
      await fn(current);
    } catch {
      if (current()) setError(true);
    } finally {
      lock.current = false;
      if (current()) setBusy(false);
    }
  }
  async function load() {
    await operation(async (current) => {
      const [runResult, archiveResult, templateResult] = await Promise.all([
        evaluationApi<unknown>(base + "/review-runs"),
        evaluationApi<unknown>(base + "/" + namespace),
        kind === "report"
          ? evaluationApi<unknown>(base + "/independent-report-templates")
          : Promise.resolve(null),
      ]);
      const safeRuns = runsSchema.parse(runResult).runs,
        safeHistory = parseIndependentHistory(kind, archiveResult, projectId),
        safeTemplates =
          kind === "report" ? parseIndependentTemplates(templateResult) : [];
      if (current()) {
        setLoadRevision((v) => v + 1);
        setRuns(safeRuns);
        setHistory(safeHistory);
        setTemplates(safeTemplates);
        setTemplateId("");
        setStaged([]);
        setBaseline(null);
        setRetest(null);
        setParent(null);
        setOpened(null);
      }
    });
  }
  function finish(
    receipt: IndependentArchive,
    remembered: PendingIndependentArchive,
    current: () => boolean,
  ) {
    if (!current() || pendingArchives.get(key) !== remembered) return;
    pendingArchives.delete(key);
    setPending(null);
    setOpened(receipt);
    setStaged([]);
    setBaseline(null);
    setRetest(null);
    setParent(null);
  }
  async function reconcile() {
    const remembered = pendingArchives.get(key);
    if (!remembered) return;
    await operation(async (current) => {
      const receipt = parseIndependentReceipt(
        await evaluationApi<unknown>(
          base + "/" + namespace + "/" + remembered.id,
        ),
        remembered,
      );
      finish(receipt, remembered, current);
    });
  }
  const template = templates.find((t) => t.id === templateId);
  const ready =
    kind === "report"
      ? staged.length > 0 && !!template && title.trim().length > 0
      : !!baseline &&
        !!retest &&
        baseline.run_id !== retest.run_id &&
        baseline.component_id === retest.component_id;
  async function create() {
    if (
      lock.current ||
      writeLock.current ||
      pendingArchives.has(key) ||
      !confirmed ||
      !ready
    )
      return;
    const id = crypto.randomUUID().replaceAll("-", "");
    const remembered: PendingIndependentArchive =
      kind === "report"
        ? {
            kind,
            id,
            projectId,
            request: {
              title: title.trim(),
              template_id: template!.id,
              template_version: template!.version,
              sources: staged.map(sourceReference),
              supersedes_id: parent?.id ?? null,
              confirmed: true,
            },
            ...(parent
              ? {
                  parent: {
                    id: parent.id,
                    root_id: parent.root_id,
                    revision: parent.revision,
                  },
                }
              : {}),
          }
        : {
            kind,
            id,
            projectId,
            request: {
              baseline: sourceReference(baseline!),
              retest: sourceReference(retest!),
              confirmed: true,
            },
          };
    // Store before any await; late responses cannot clear a different scope's pending ID.
    pendingArchives.set(key, remembered);
    setPending(remembered);
    writeLock.current = true;
    try {
      await operation(async (current) => {
        const receipt = parseIndependentReceipt(
          await evaluationApi<unknown>(
            base + "/" + namespace + "/" + id,
            remembered.request,
            "PUT",
          ),
          remembered,
        );
        finish(receipt, remembered, current);
      });
    } finally {
      writeLock.current = false;
    }
  }
  async function open() {
    if (!assessmentIdValid(lookup)) return;
    const id = lookup;
    setOpened(null);
    await operation(async (current) => {
      const receipt = parseIndependentArchive(
        kind,
        await evaluationApi<unknown>(base + "/" + namespace + "/" + id),
        projectId,
        id,
      );
      if (current()) setOpened(receipt);
    });
  }
  function add(source: IndependentSource, slot?: "baseline" | "retest") {
    revoke();
    if (slot === "baseline") setBaseline(source);
    else if (slot === "retest") setRetest(source);
    else if (
      staged.length < 10 &&
      !staged.some((s) => s.component_id === source.component_id)
    )
      setStaged((old) => [...old, source]);
  }
  function download(format: "md" | "json") {
    if (!opened || locked) return;
    const value =
      format === "md" && "markdown" in opened
        ? opened.markdown
        : JSON.stringify(opened, null, 2);
    const url = URL.createObjectURL(
      new Blob([value], {
        type:
          format === "md" ? "text/markdown;charset=utf-8" : "application/json",
      }),
    );
    try {
      const a = document.createElement("a");
      a.href = url;
      a.download = "independent-" + kind + "-" + opened.id + "." + format;
      a.click();
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  return (
    <div className="min-w-0 space-y-4">
      <Button variant="outline" disabled={locked} onClick={() => void load()}>
        {zh
          ? "加载独立运行、模板和档案"
          : "Load independent runs, templates and archives"}
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {zh
            ? "操作未确认，请核对权限、来源或并发变更。写入不自动重试；404 也不清除待核对 ID，只能显式读取同一 ID 收据。"
            : "Operation unconfirmed. Check permissions, sources or concurrent changes. Never retry a write; even 404 retains the pending ID for explicit same-ID GET reconciliation."}
        </p>
      )}
      {pending && (
        <div role="status" className="space-y-2 rounded-md border p-3 text-sm">
          <p>
            {zh
              ? "待核对独立档案 ID（离页前请保留；不要重新提交）："
              : "Pending independent archive ID (keep before leaving; do not resubmit):"}{" "}
            <code className="break-all">{pending.id}</code>
          </p>
          <Button disabled={busy} onClick={() => void reconcile()}>
            {zh
              ? "读取同一 ID 独立档案收据"
              : "Check same-ID independent archive receipt"}
          </Button>
        </div>
      )}
      <fieldset disabled={locked} className="min-w-0 space-y-4">
        <HistoricalSourcePicker
          key={loadRevision}
          projectId={projectId}
          runs={runs}
          zh={zh}
          operation={operation}
          revoke={revoke}
          onAdd={add}
          kind={kind}
          staged={staged}
        />
        {kind === "report" ? (
          <>
            <ul
              aria-label={zh ? "独立报告组件" : "Independent report components"}
              className="space-y-2"
            >
              {staged.map((s) => (
                <li
                  key={s.component_id}
                  className="min-w-0 space-y-2 rounded-md border p-3"
                >
                  <HistoricalSourceView source={s} zh={zh} />
                  <Button
                    variant="outline"
                    onClick={() => {
                      setStaged(
                        staged.filter((v) => v.component_id !== s.component_id),
                      );
                      revoke();
                    }}
                  >
                    {zh ? "移除组件" : "Remove component"} {s.component_name}
                  </Button>
                </li>
              ))}
            </ul>
            <label className="block space-y-1 text-sm">
              {zh ? "独立报告标题" : "Independent report title"}
              <Input
                aria-label={zh ? "独立报告标题" : "Independent report title"}
                maxLength={160}
                value={title}
                onChange={(e) => {
                  setTitle(e.target.value);
                  revoke();
                }}
              />
            </label>
            <label className="block space-y-1 text-sm">
              {zh ? "独立固定模板" : "Independent pinned template"}
              <select
                aria-label={zh ? "独立固定模板" : "Independent pinned template"}
                className={selectClass}
                value={templateId}
                onChange={(e) => {
                  setTemplateId(e.target.value);
                  revoke();
                }}
              >
                <option value="">{zh ? "选择模板" : "Choose template"}</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.id}@{t.version}
                  </option>
                ))}
              </select>
            </label>
            {parent && (
              <div className="text-sm break-all">
                {zh ? "后继草稿的父档案：" : "Parent for successor draft:"}{" "}
                {parent.id} · r{parent.revision}
                <Button
                  variant="outline"
                  onClick={() => {
                    setParent(null);
                    revoke();
                  }}
                >
                  {zh ? "清除父档案" : "Clear parent archive"}
                </Button>
              </div>
            )}
          </>
        ) : (
          <>
            {(["baseline", "retest"] as const).map((side) => (
              <div key={side} className="min-w-0 rounded-md border p-3">
                <h3>
                  {side === "baseline"
                    ? zh
                      ? "冻结基线"
                      : "Frozen baseline"
                    : zh
                      ? "冻结复测"
                      : "Frozen retest"}
                </h3>
                {(side === "baseline" ? baseline : retest) ? (
                  <>
                    <HistoricalSourceView
                      source={(side === "baseline" ? baseline : retest)!}
                      zh={zh}
                    />
                    <Button
                      variant="outline"
                      onClick={() => {
                        if (side === "baseline") setBaseline(null);
                        else setRetest(null);
                        revoke();
                      }}
                    >
                      {zh ? "清除" : "Clear"} {side}
                    </Button>
                  </>
                ) : (
                  <p>{zh ? "尚未选择" : "Not selected"}</p>
                )}
              </div>
            ))}
            <p className="text-muted-foreground text-sm">
              {zh
                ? "同基准、预算、标准、版本和非重叠时间由服务端最终验证；客户端选择不代表已符合。"
                : "The server finally verifies benchmark, budgets, criteria, distinct versions and non-overlapping chronology. Client selection is not proof of compatibility."}
            </p>
          </>
        )}
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={confirmed}
            disabled={!ready}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            {zh
              ? "我已查看指定历史独立评估，确认创建不可变且未批准的草稿；不发起模型或目标请求。"
              : "I viewed the selected historical independent assessments and confirm an immutable, not-approved draft; no model or target request."}
          </span>
        </label>
        <Button disabled={!ready || !confirmed} onClick={() => void create()}>
          {zh
            ? kind === "report"
              ? "创建独立报告草稿"
              : "创建独立复测比较"
            : kind === "report"
              ? "Create independent report draft"
              : "Create independent retest comparison"}
        </Button>
        <hr />
        <label className="block space-y-1 text-sm">
          {zh ? "独立历史档案" : "Independent archive history"}
          <select
            aria-label={zh ? "独立历史档案" : "Independent archive history"}
            className={selectClass}
            value={lookup}
            onChange={(e) => {
              setLookup(e.target.value);
              setOpened(null);
              revoke();
            }}
          >
            <option value="">
              {zh ? "选择档案（最多 100）" : "Choose archive (up to 100)"}
            </option>
            {history.map((h) => (
              <option key={h.id} value={h.id}>
                {"title" in h
                  ? h.title
                  : h.baseline_label + " → " + h.retest_label}{" "}
                · {h.id}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1 text-sm">
          {zh ? "已知独立档案 ID" : "Known independent archive ID"}
          <Input
            aria-label={zh ? "已知独立档案 ID" : "Known independent archive ID"}
            value={lookup}
            maxLength={32}
            onChange={(e) => {
              setLookup(e.target.value);
              setOpened(null);
              revoke();
            }}
          />
        </label>
        <Button
          variant="outline"
          disabled={!assessmentIdValid(lookup)}
          onClick={() => void open()}
        >
          {zh ? "打开固定独立档案" : "Open pinned independent archive"}
        </Button>
      </fieldset>
      {opened && (
        <section
          aria-label={
            zh
              ? "已打开的独立历史档案"
              : "Opened independent historical archive"
          }
          className="min-w-0 space-y-3 rounded-md border p-3 text-sm"
        >
          <h3 className="font-semibold">
            {zh
              ? "不可变历史草稿 / 未批准"
              : "Immutable historical draft / not approved"}
          </h3>
          <code className="block break-all">
            {opened.id} · {opened.archive_hash}
          </code>
          {("components" in opened
            ? opened.components
            : [opened.baseline, opened.retest]
          ).map((s, i) => (
            <HistoricalSourceView key={i} source={s} zh={zh} />
          ))}
          {"markdown" in opened ? (
            <>
              <pre className="max-h-96 max-w-full overflow-auto break-all whitespace-pre-wrap">
                {opened.markdown}
              </pre>
              <Button
                variant="outline"
                disabled={locked}
                onClick={() => {
                  setParent(opened);
                  revoke();
                }}
              >
                {zh ? "用作新修订的父档案" : "Use as parent of a new revision"}
              </Button>
              <Button
                variant="outline"
                disabled={locked}
                onClick={() => download("md")}
              >
                {zh ? "下载历史 Markdown" : "Download historical Markdown"}
              </Button>
            </>
          ) : (
            <>
              <p>
                {zh ? "全样本通过率差值" : "All-sample pass-rate delta"}:{" "}
                {opened.pass_rate_delta.numerator} /{" "}
                {opened.pass_rate_delta.denominator} ·{" "}
                {(opened.pass_rate_delta.value * 100).toFixed(2)} pp
              </p>
              <pre className="max-h-96 max-w-full overflow-auto break-all whitespace-pre-wrap">
                {JSON.stringify(
                  {
                    benchmark: opened.benchmark,
                    transitions: opened.transitions,
                    cases: opened.cases,
                  },
                  null,
                  2,
                )}
              </pre>
            </>
          )}
          <Button
            variant="outline"
            disabled={locked}
            onClick={() => download("json")}
          >
            {zh ? "下载历史 JSON" : "Download historical JSON"}
          </Button>
          <p>
            {zh
              ? "独立 Word/PDF 和正式批准尚未交付；旧 Word 路由不用于此档案。"
              : "Independent Word/PDF and formal approval are not delivered; the legacy Word route is not used for this archive."}
          </p>
        </section>
      )}
    </div>
  );
}
function HistoricalSourcePicker({
  projectId,
  runs,
  zh,
  operation,
  revoke,
  onAdd,
  kind,
  staged,
}: {
  projectId: string;
  runs: Run[];
  zh: boolean;
  operation: Operation;
  revoke: () => void;
  onAdd: (source: IndependentSource, slot?: "baseline" | "retest") => void;
  kind: ArchiveKind;
  staged: IndependentSource[];
}) {
  const localEpoch = useRef(0);
  useEffect(() => {
    const ref = localEpoch;
    return () => {
      ref.current++;
    };
  }, []);
  const [run, setRun] = useState(""),
    [history, setHistory] = useState<AssessmentMetadata[]>([]),
    [id, setId] = useState(""),
    [opened, setOpened] = useState<AssessmentArchive | null>(null);
  const base =
    "evaluation/projects/" +
    encodeURIComponent(projectId) +
    "/review-runs/" +
    encodeURIComponent(run) +
    "/assessments";
  async function load() {
    const token = localEpoch.current;
    setOpened(null);
    setHistory([]);
    setId("");
    await operation(async (current) => {
      const rows = parseAssessmentHistory(
        await evaluationApi<unknown>(base),
        projectId,
        run,
      );
      if (current() && token === localEpoch.current) setHistory(rows);
    });
  }
  async function open() {
    const token = localEpoch.current;
    setOpened(null);
    await operation(async (current) => {
      const receipt = parseAssessmentArchive(
        await evaluationApi<unknown>(base + "/" + id),
        projectId,
        run,
        id,
      );
      if (current() && token === localEpoch.current) setOpened(receipt);
    });
  }
  const eligible =
    opened?.assessment.readiness === "review_complete" &&
    !opened.assessment.blockers.length;
  return (
    <div className="min-w-0 space-y-3 rounded-md border p-3">
      <label className="block space-y-1 text-sm">
        {zh ? "历史评估运行" : "Historical assessment run"}
        <select
          aria-label={zh ? "历史评估运行" : "Historical assessment run"}
          className={selectClass}
          value={run}
          onChange={(e) => {
            setRun(e.target.value);
            setId("");
            setHistory([]);
            setOpened(null);
            revoke();
          }}
        >
          <option value="">{zh ? "选择运行" : "Choose run"}</option>
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {r.component_name} · {r.plan_label} · {r.id}
            </option>
          ))}
        </select>
      </label>
      <Button variant="outline" disabled={!run} onClick={() => void load()}>
        {zh
          ? "加载历史独立评估修订"
          : "Load historical independent assessment revisions"}
      </Button>
      <label className="block space-y-1 text-sm">
        {zh ? "明确选择历史修订" : "Explicit historical revision"}
        <select
          aria-label={zh ? "明确选择历史修订" : "Explicit historical revision"}
          className={selectClass}
          value={id}
          onChange={(e) => {
            setId(e.target.value);
            setOpened(null);
            revoke();
          }}
        >
          <option value="">
            {zh
              ? "选择修订（不默认最新）"
              : "Choose revision (no latest default)"}
          </option>
          {history.map((h) => (
            <option key={h.id} value={h.id}>
              r{h.revision} · {h.id}
            </option>
          ))}
        </select>
      </label>
      <label className="block space-y-1 text-sm">
        {zh ? "历史评估修订 ID" : "Historical assessment revision ID"}
        <Input
          aria-label={
            zh ? "历史评估修订 ID" : "Historical assessment revision ID"
          }
          maxLength={32}
          value={id}
          onChange={(e) => {
            setId(e.target.value);
            setOpened(null);
            revoke();
          }}
        />
      </label>
      <Button
        variant="outline"
        disabled={!run || !assessmentIdValid(id)}
        onClick={() => void open()}
      >
        {zh ? "打开指定历史评估" : "Open selected historical assessment"}
      </Button>
      {opened && (
        <section
          aria-label={zh ? "已查看的来源评估" : "Viewed source assessment"}
          className="min-w-0 space-y-3 text-sm"
        >
          <HistoricalSourceView source={archivedSource(opened)} zh={zh} />
          {!eligible && (
            <p>
              {zh
                ? "临时评估不能作为档案来源；不自动替换为其他修订。"
                : "Provisional assessments are ineligible archive sources; never substitute another revision automatically."}
            </p>
          )}
          {kind === "report" ? (
            <Button
              variant="outline"
              disabled={
                !eligible ||
                staged.length >= 10 ||
                staged.some(
                  (s) => s.component_id === opened.assessment.component_id,
                )
              }
              onClick={() => onAdd(archivedSource(opened))}
            >
              {zh ? "加入独立报告组件" : "Add independent report component"}
            </Button>
          ) : (
            <>
              {(["baseline", "retest"] as const).map((slot) => (
                <Button
                  key={slot}
                  variant="outline"
                  disabled={!eligible}
                  onClick={() => onAdd(archivedSource(opened), slot)}
                >
                  {slot === "baseline"
                    ? zh
                      ? "设为历史基线"
                      : "Use as historical baseline"
                    : zh
                      ? "设为历史复测"
                      : "Use as historical retest"}
                </Button>
              ))}
            </>
          )}
        </section>
      )}
    </div>
  );
}
function HistoricalSourceView({
  source: s,
  zh,
}: {
  source: IndependentSource;
  zh: boolean;
}) {
  return (
    <div className="min-w-0 space-y-1 text-sm break-words">
      <p>
        {s.component_name} · {s.plan_label}
      </p>
      <p>
        {s.human_pass_rate.numerator} / {s.human_pass_rate.denominator} ·{" "}
        {(s.human_pass_rate.value * 100).toFixed(2)}% · {s.readiness} ·
        not_approved
      </p>
      <p>
        {zh
          ? "全部冻结样本分母；历史评估，不是当前任务状态或正式批准。"
          : "ALL frozen samples; historical assessment, not current task state or formal approval."}
      </p>
      <code className="block break-all">
        {s.run_id} · {s.assessment_ref.assessment_id} · r
        {s.assessment_ref.assessment_revision}
      </code>
      <code className="block break-all">
        {s.assessment_ref.assessment_hash} · {s.summary_hash}
      </code>
      <EvaluationCriteriaView assessment={s.criteria_evaluation} zh={zh} />
    </div>
  );
}
