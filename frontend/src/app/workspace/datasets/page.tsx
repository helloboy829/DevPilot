"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { EvaluationExecutionPanel } from "@/components/workspace/evaluation-execution-panel";
import { EvaluationPlanPanel } from "@/components/workspace/evaluation-plan-panel";
import { EvaluationReviewPanel } from "@/components/workspace/evaluation-review-panel";
import { IndependentAssessmentPanel } from "@/components/workspace/independent-assessment-panel";
import { ProjectRegistryPanel } from "@/components/workspace/project-registry-panel";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import type {
  DataAuditEvent,
  DatasetVersion,
  EvaluationProject,
  QASample,
} from "@/core/datasets/types";
import { evaluationApi } from "@/core/evaluation/api";
import type { PendingAssessments } from "@/core/evaluation/assessment-policy";
import type { PendingReviewTasks } from "@/core/evaluation/task-types";
import { useI18n } from "@/core/i18n/hooks";

const example =
  '[{"sample_id":"q1","input":"Synthetic question","expected":"Synthetic reference answer","source_ref":"record:1","slice_tag":"default"}]';
const root = "evaluation/projects";
const selectStyle = "bg-background w-full rounded-md border px-3 py-2 text-sm";

export default function DatasetsPage() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const [projects, setProjects] = useState<EvaluationProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [datasets, setDatasets] = useState<DatasetVersion[]>([]);
  const [dataset, setDataset] = useState<DatasetVersion | null>(null);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState<"baseline" | "acceptance">("baseline");
  const [sourceLabel, setSourceLabel] = useState("");
  const [sourceRef, setSourceRef] = useState("");
  const [basis, setBasis] = useState("");
  const [attested, setAttested] = useState(false);
  const [content, setContent] = useState("");
  const [format, setFormat] = useState<"json" | "jsonl">("json");
  const [samples, setSamples] = useState<QASample[] | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [audit, setAudit] = useState<DataAuditEvent[] | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pendingReviewTasks = useRef<PendingReviewTasks>(new Map());
  const pendingAssessments = useRef<PendingAssessments>(new Map());
  const epoch = useRef(0);
  const lock = useRef(false);

  useEffect(() => {
    const lifecycle = epoch;
    const current = ++lifecycle.current;
    void evaluationApi<{ projects: EvaluationProject[] }>(root)
      .then((data) => {
        if (current === epoch.current) setProjects(data.projects);
      })
      .catch(() => {
        if (current === epoch.current)
          setError(
            "Operation failed; check permissions, persistence and reload.",
          );
      })
      .finally(() => {
        if (current === epoch.current) setBusy(false);
      });
    return () => {
      lifecycle.current++;
    };
  }, []);

  function clearSensitive() {
    setContent("");
    setSamples(null);
    setReviewed(false);
    setAudit(null);
    setNotice("");
  }

  async function operate(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    const current = epoch.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch {
      if (current === epoch.current) {
        setReviewed(false);
        setError(
          zh
            ? "操作失败：请检查权限、数据格式或版本冲突，重新加载后再审核。"
            : "Operation failed; check permissions, data format or revision conflicts, then reload and review.",
        );
      }
    } finally {
      lock.current = false;
      if (current === epoch.current) setBusy(false);
    }
  }

  function acceptDataset(next: DatasetVersion) {
    setDataset(next);
    setDatasets((rows) => [...rows.filter((row) => row.id !== next.id), next]);
    clearSensitive();
  }

  const base = `${root}/${encodeURIComponent(projectId)}/datasets`;
  const path = dataset ? `${base}/${encodeURIComponent(dataset.id)}` : "";
  const frozen = dataset?.status === "frozen";

  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {zh ? "项目与数据" : "Projects & datasets"}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-8">
          <section className="rounded-xl border bg-sky-500/5 p-5">
            <h2 className="font-semibold">
              {zh
                ? "先确认数据质量，再开展评测"
                : "Review data quality before evaluation"}
            </h2>
            <p className="text-muted-foreground mt-2 text-sm leading-6">
              {zh
                ? "QA 数据最小闭环：来源声明 → 人工导入 → 查看问题 / 预期答案 / 来源 → 人工确认冻结。不会调用模型、抓取来源或自动运行测试。冻结不是验收通过，也不是双人独立审核。"
                : "QA foundation: source declaration → manual import → Q / reference / source review → confirmed freeze. No model calls, source retrieval or test execution. Frozen is neither acceptance nor independent two-person review."}
            </p>
            <p className="text-muted-foreground mt-2 text-sm">
              {zh
                ? "仅显示本人项目；预期答案单独存储、单独授权读取。不写入聊天或浏览器持久缓存。"
                : "Owner-only projects. Reference answers use separate storage and read permission; no chat or persistent browser cache."}
            </p>
          </section>
          {error && (
            <p
              role="alert"
              className="text-destructive rounded-md border p-3 text-sm"
            >
              {error}
            </p>
          )}
          {notice && (
            <p role="status" className="rounded-md border p-3 text-sm">
              {notice}
            </p>
          )}
          <fieldset
            disabled={busy}
            className="grid min-w-0 gap-6 lg:grid-cols-[280px_minmax(0,1fr)]"
          >
            <aside className="min-w-0 space-y-5 rounded-xl border p-4">
              <label className="grid gap-2 text-sm">
                {zh ? "选择项目" : "Select project"}
                <select
                  className={selectStyle}
                  value={projectId}
                  onChange={(event) => {
                    const id = event.target.value;
                    setProjectId(id);
                    setDatasets([]);
                    setDataset(null);
                    clearSensitive();
                    if (id)
                      void operate(async () => {
                        setDatasets(
                          (
                            await evaluationApi<{ datasets: DatasetVersion[] }>(
                              `${root}/${encodeURIComponent(id)}/datasets`,
                            )
                          ).datasets,
                        );
                      });
                  }}
                >
                  <option value="">{zh ? "请选择" : "Select"}</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm">
                {zh ? "项目名称" : "Project name"}
                <Input
                  maxLength={160}
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                />
              </label>
              <Button
                disabled={!projectName.trim()}
                onClick={() =>
                  void operate(async () => {
                    const project = await evaluationApi<EvaluationProject>(
                      root,
                      { name: projectName },
                    );
                    setProjects((rows) => [...rows, project]);
                    setProjectId(project.id);
                    setProjectName("");
                    setDatasets([]);
                    setDataset(null);
                    clearSensitive();
                  })
                }
              >
                {zh ? "创建项目" : "Create project"}
              </Button>
              <div className="space-y-2 border-t pt-4">
                <h2 className="text-sm font-semibold">
                  {zh ? "数据版本" : "Dataset versions"}
                </h2>
                {datasets.map((row) => (
                  <button
                    key={row.id}
                    type="button"
                    aria-pressed={dataset?.id === row.id}
                    className={`w-full rounded-md border p-3 text-left text-sm break-words ${dataset?.id === row.id ? "border-primary bg-primary/5" : ""}`}
                    onClick={() => {
                      setDataset(row);
                      clearSensitive();
                    }}
                  >
                    <span className="block font-medium">{row.name}</span>
                    <span className="text-muted-foreground text-xs">
                      {row.status} · r{row.revision} · {row.sample_count}{" "}
                      {zh ? "条" : "samples"}
                    </span>
                  </button>
                ))}
                {projectId && (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setDataset(null);
                      clearSensitive();
                    }}
                  >
                    {zh ? "新建数据版本" : "New dataset version"}
                  </Button>
                )}
              </div>
              <Button
                variant="outline"
                onClick={() =>
                  void operate(async () => {
                    clearSensitive();
                    setProjects(
                      (
                        await evaluationApi<{ projects: EvaluationProject[] }>(
                          root,
                        )
                      ).projects,
                    );
                    if (projectId) {
                      const rows = (
                        await evaluationApi<{ datasets: DatasetVersion[] }>(
                          base,
                        )
                      ).datasets;
                      setDatasets(rows);
                      setDataset(
                        rows.find((row) => row.id === dataset?.id) ?? null,
                      );
                    }
                  })
                }
              >
                {zh ? "重新加载" : "Reload"}
              </Button>
            </aside>
            <main className="min-w-0 space-y-5">
              {!projectId && (
                <p className="text-muted-foreground rounded-xl border p-6 text-sm">
                  {zh
                    ? "创建或选择一个项目后，登记授权来源并导入 QA 数据。"
                    : "Create or select a project, declare an authorized source, then import QA data."}
                </p>
              )}
              {projectId && !dataset && (
                <section className="grid gap-4 rounded-xl border p-5">
                  <h2 className="font-semibold">
                    {zh ? "登记新数据版本" : "Register a dataset version"}
                  </h2>
                  <label className="grid gap-2 text-sm">
                    {zh ? "数据集名称" : "Dataset name"}
                    <Input
                      maxLength={160}
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </label>
                  <label className="grid gap-2 text-sm">
                    {zh ? "用途" : "Purpose"}
                    <select
                      className={selectStyle}
                      value={purpose}
                      onChange={(e) =>
                        setPurpose(e.target.value as typeof purpose)
                      }
                    >
                      <option value="baseline">BASELINE</option>
                      <option value="acceptance">ACCEPTANCE</option>
                    </select>
                  </label>
                  <label className="grid gap-2 text-sm">
                    {zh ? "来源名称" : "Source label"}
                    <Input
                      maxLength={160}
                      value={sourceLabel}
                      onChange={(e) => {
                        setSourceLabel(e.target.value);
                        setAttested(false);
                      }}
                    />
                  </label>
                  <label className="grid gap-2 text-sm">
                    {zh ? "来源引用（不会自动访问）" : "Source reference"}
                    <Input
                      maxLength={500}
                      value={sourceRef}
                      onChange={(e) => {
                        setSourceRef(e.target.value);
                        setAttested(false);
                      }}
                    />
                  </label>
                  <label className="grid gap-2 text-sm">
                    {zh ? "授权依据" : "Authorization basis"}
                    <Textarea
                      maxLength={1000}
                      value={basis}
                      onChange={(e) => {
                        setBasis(e.target.value);
                        setAttested(false);
                      }}
                    />
                  </label>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={attested}
                      onChange={(e) => setAttested(e.target.checked)}
                    />
                    {zh
                      ? "我确认来源允许本次评测使用；这只是声明，不代表平台已核验授权。"
                      : "I confirm the source permits this evaluation use; this declaration is not platform verification."}
                  </label>
                  <Button
                    disabled={
                      !name.trim() ||
                      !sourceLabel.trim() ||
                      !sourceRef.trim() ||
                      !basis.trim() ||
                      !attested
                    }
                    onClick={() =>
                      void operate(async () => {
                        acceptDataset(
                          await evaluationApi<DatasetVersion>(base, {
                            name,
                            purpose,
                            source: {
                              label: sourceLabel,
                              reference: sourceRef,
                              authorization_basis: basis,
                              attested,
                            },
                          }),
                        );
                        setName("");
                        setSourceLabel("");
                        setSourceRef("");
                        setBasis("");
                        setAttested(false);
                      })
                    }
                  >
                    {zh ? "创建数据集" : "Create dataset"}
                  </Button>
                </section>
              )}
              {dataset && (
                <>
                  <section className="space-y-3 rounded-xl border p-5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h2 className="font-semibold">{dataset.name}</h2>
                      <span
                        data-testid="dataset-status"
                        className="rounded border px-2 py-1 text-sm"
                      >
                        {frozen
                          ? zh
                            ? "已冻结"
                            : "Frozen"
                          : zh
                            ? "草稿"
                            : "Draft"}
                      </span>
                    </div>
                    <p className="text-sm">
                      {dataset.purpose.toUpperCase()} · r{dataset.revision} ·{" "}
                      {dataset.sample_count} {zh ? "条样本" : "samples"}
                    </p>
                    <dl className="grid gap-2 text-sm">
                      <dt className="font-medium">
                        {zh
                          ? "来源与授权声明"
                          : "Source & authorization declaration"}
                      </dt>
                      <dd className="break-words whitespace-pre-wrap">
                        {dataset.source.label} / {dataset.source.reference}
                      </dd>
                      <dd className="break-words whitespace-pre-wrap">
                        {dataset.source.authorization_basis}
                      </dd>
                    </dl>
                    {dataset.content_hash && (
                      <p className="text-muted-foreground font-mono text-xs break-all">
                        SHA-256: {dataset.content_hash}
                      </p>
                    )}
                    {frozen && (
                      <p className="text-muted-foreground text-sm">
                        {zh
                          ? "冻结后不可覆盖；如需修改，请新建数据版本。此状态不等于测试通过。"
                          : "Frozen versions cannot be overwritten. Create a new version for changes. This is not a test verdict."}
                      </p>
                    )}
                  </section>
                  {!frozen && (
                    <section className="space-y-4 rounded-xl border p-5">
                      <h2 className="font-semibold">
                        {zh
                          ? "导入 QA（全量替换草稿）"
                          : "Import QA (replace entire draft)"}
                      </h2>
                      <p className="text-muted-foreground text-sm">
                        {zh
                          ? "最多 500 条、UTF-8 内容 500 KB；每条需要 sample_id、input、expected、source_ref。拒绝重复 ID / 规范化问题及空金标；任一错误则整批不写入。请勿包含密钥或不必要的个人信息。"
                          : "Up to 500 samples and 500 KB UTF-8 content. Required: sample_id, input, expected, source_ref. Duplicate IDs / normalized questions and empty answers are rejected atomically. Do not include credentials or unnecessary personal data."}
                      </p>
                      <label className="grid gap-2 text-sm">
                        {zh ? "格式" : "Format"}
                        <select
                          className={selectStyle}
                          value={format}
                          onChange={(e) =>
                            setFormat(e.target.value as typeof format)
                          }
                        >
                          <option value="json">JSON array</option>
                          <option value="jsonl">JSONL</option>
                        </select>
                      </label>
                      <label className="grid gap-2 text-sm">
                        {zh ? "QA 导入内容" : "QA import"}
                        <Textarea
                          className="min-h-48 font-mono text-xs"
                          maxLength={500000}
                          value={content}
                          placeholder={example}
                          onChange={(e) => {
                            setContent(e.target.value);
                            setSamples(null);
                            setReviewed(false);
                          }}
                        />
                      </label>
                      <details className="text-muted-foreground text-xs">
                        <summary>
                          {zh
                            ? "查看合成格式示例"
                            : "View synthetic schema example"}
                        </summary>
                        <pre className="mt-2 break-all whitespace-pre-wrap">
                          {example}
                        </pre>
                      </details>
                      <Button
                        disabled={!content.trim()}
                        onClick={() =>
                          void operate(async () => {
                            acceptDataset(
                              await evaluationApi<DatasetVersion>(
                                `${path}/samples`,
                                { revision: dataset.revision, format, content },
                                "PUT",
                              ),
                            );
                            setNotice(
                              zh
                                ? "已原子保存，请重新读取并审核后冻结。"
                                : "Saved atomically. Load and review the persisted samples before freezing.",
                            );
                          })
                        }
                      >
                        {zh ? "替换草稿样本" : "Replace draft samples"}
                      </Button>
                    </section>
                  )}
                  <section className="space-y-4 rounded-xl border p-5">
                    <h2 className="font-semibold">
                      {zh ? "人工检查与冻结" : "Manual review & freeze"}
                    </h2>
                    <Button
                      variant="outline"
                      disabled={
                        dataset.sample_count === 0 || content.trim().length > 0
                      }
                      onClick={() =>
                        void operate(async () => {
                          const result = await evaluationApi<{
                            samples: QASample[];
                          }>(`${path}/references`);
                          setSamples(result.samples);
                          setReviewed(false);
                        })
                      }
                    >
                      {zh
                        ? "读取问题 / 预期 / 来源"
                        : "Load Q / reference / source"}
                    </Button>
                    {samples && (
                      <div className="max-h-[32rem] overflow-auto rounded-md border">
                        <table className="w-full table-fixed text-left text-sm">
                          <thead className="bg-muted sticky top-0">
                            <tr>
                              {[
                                "ID",
                                zh ? "输入 Q" : "Input Q",
                                zh ? "预期答案" : "Reference answer",
                                zh ? "来源 / 切片" : "Source / slice",
                              ].map((heading) => (
                                <th key={heading} className="p-3">
                                  {heading}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {samples.map((s) => (
                              <tr
                                key={s.sample_id}
                                className="border-t align-top"
                              >
                                <td className="p-3 break-words">
                                  {s.sample_id}
                                </td>
                                <td className="p-3 break-words whitespace-pre-wrap">
                                  {s.input}
                                </td>
                                <td className="p-3 break-words whitespace-pre-wrap">
                                  {s.expected}
                                </td>
                                <td className="p-3 break-words whitespace-pre-wrap">
                                  {s.source_ref}
                                  <br />
                                  {s.slice_tag}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                    {!frozen && (
                      <>
                        <label className="flex items-start gap-2 text-sm">
                          <input
                            type="checkbox"
                            disabled={
                              samples?.length !== dataset.sample_count ||
                              !!content.trim()
                            }
                            checked={reviewed}
                            onChange={(e) => setReviewed(e.target.checked)}
                          />
                          {zh
                            ? "我已检查所有样本、预期答案与来源，并确认冻结当前版本（允许本人自审，不是独立双人审核）。"
                            : "I reviewed all samples, reference answers and sources and confirm this version (self-review, not independent two-person approval)."}
                        </label>
                        <Button
                          disabled={
                            !reviewed ||
                            !dataset.content_hash ||
                            !!content.trim()
                          }
                          onClick={() =>
                            void operate(async () => {
                              acceptDataset(
                                await evaluationApi<DatasetVersion>(
                                  `${path}/freeze`,
                                  {
                                    revision: dataset.revision,
                                    content_hash: dataset.content_hash,
                                    reviewed: true,
                                  },
                                ),
                              );
                            })
                          }
                        >
                          {zh ? "冻结已审核版本" : "Freeze reviewed version"}
                        </Button>
                      </>
                    )}
                    <Button
                      variant="outline"
                      onClick={() =>
                        void operate(async () => {
                          setAudit(
                            (
                              await evaluationApi<{ events: DataAuditEvent[] }>(
                                `${path}/audit`,
                              )
                            ).events,
                          );
                        })
                      }
                    >
                      {zh ? "查看操作记录" : "View activity"}
                    </Button>
                    {audit && (
                      <ul className="space-y-2 text-xs">
                        {audit.map((event) => (
                          <li
                            key={event.id}
                            className="rounded border p-2 break-all"
                          >
                            {event.at} · {event.action} · r{event.revision} ·{" "}
                            {event.actor}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </>
              )}
            </main>
          </fieldset>
          {projectId && (
            <ProjectRegistryPanel
              key={`registry:${projectId}`}
              projectId={projectId}
              zh={zh}
            />
          )}
          {projectId && (
            <EvaluationPlanPanel
              key={`plan:${projectId}`}
              projectId={projectId}
              zh={zh}
            />
          )}
          {projectId && (
            <EvaluationExecutionPanel
              key={"execute:" + projectId}
              projectId={projectId}
              zh={zh}
            />
          )}
          {projectId && (
            <EvaluationReviewPanel
              key={"review:" + projectId}
              pendingTasks={pendingReviewTasks.current}
              projectId={projectId}
              zh={zh}
            />
          )}
          {projectId && (
            <IndependentAssessmentPanel
              projectId={projectId}
              pendingAssessments={pendingAssessments.current}
              zh={zh}
            />
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
