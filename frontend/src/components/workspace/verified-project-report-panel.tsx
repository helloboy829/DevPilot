"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EvaluationCriteriaView } from "@/components/workspace/evaluation-criteria-view";
import type { EvaluationProject } from "@/core/datasets/types";
import { evaluationApi, evaluationReportDocx } from "@/core/evaluation/api";
import type {
  ArchiveMetadata,
  ArchiveTemplate,
  PendingArchive,
  ReportArchive,
} from "@/core/evaluation/report-archive-types";
import type { ReviewRun, ReviewSummary } from "@/core/evaluation/review-types";

const selectClass =
  "bg-background w-full min-w-0 rounded-md border p-2 text-sm";

/** Pending write identifiers survive project switches in this page, never browser storage. */
export function VerifiedProjectReportPanel({ zh }: { zh: boolean }) {
  const [projects, setProjects] = useState<EvaluationProject[]>([]);
  const [projectId, setProjectId] = useState("");
  const [pending, setPending] = useState<Record<string, PendingArchive | null>>(
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
  async function loadProjects() {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError(false);
    setProjectId("");
    setProjects([]);
    try {
      const result = await evaluationApi<{ projects: EvaluationProject[] }>(
        "evaluation/projects",
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
        zh ? "已验证平台报告存档" : "Verified platform report archive"
      }
      className="space-y-4 rounded-xl border p-4 md:p-6"
    >
      <h2 className="text-lg font-semibold">
        {zh
          ? "平台结果 → 多组件报告存档"
          : "Platform results → multi-component report archive"}
      </h2>
      <p className="text-muted-foreground text-sm">
        {zh
          ? "从平台证据生成不可变历史草稿，不手填指标、不自动批准。每组件一个已完成复核的效果运行；不跨组件平均，不包含性能或 TTFT。下方人工填报 / Agent 建议仍是独立的未验证草稿。"
          : "Immutable historical drafts from platform evidence, not supplied metrics or automatic approval. One fully reviewed effectiveness run per component. No pooled rate, performance or TTFT. Manual forms / Agent advice below remain separate unverified drafts."}
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => void loadProjects()}
        >
          {zh ? "加载项目" : "Load projects"}
        </Button>
        <label className="min-w-0 flex-1 space-y-1 text-sm">
          {zh ? "报告项目" : "Report project"}
          <select
            aria-label={zh ? "报告项目" : "Report project"}
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
      </div>
      {error && (
        <p role="alert">
          {zh
            ? "无法读取项目，请核对权限后手动刷新。"
            : "Cannot read projects; check permissions before manually refreshing."}
        </p>
      )}
      {projectId && (
        <ProjectArchiveWorkspace
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

function ProjectArchiveWorkspace({
  projectId,
  zh,
  initialPending,
  onPending,
}: {
  projectId: string;
  zh: boolean;
  initialPending: PendingArchive | null;
  onPending: (value: PendingArchive | null) => void;
}) {
  const [runs, setRuns] = useState<ReviewRun[]>([]);
  const [templates, setTemplates] = useState<ArchiveTemplate[]>([]);
  const [history, setHistory] = useState<ArchiveMetadata[]>([]);
  const [runId, setRunId] = useState("");
  const [templateKey, setTemplateKey] = useState("");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState<ReviewSummary | null>(null);
  const [staged, setStaged] = useState<ReviewSummary[]>([]);
  const [parent, setParent] = useState<ReportArchive | null>(null);
  const [opened, setOpened] = useState<ReportArchive | null>(null);
  const [pending, setPending] = useState<PendingArchive | null>(initialPending);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const lock = useRef(false);
  const epoch = useRef(0);
  const base = "evaluation/projects/" + encodeURIComponent(projectId);
  const selected = templates.find(
    (t) => t.id + "@" + t.version === templateKey,
  );
  const criteriaRequired = staged.some((s) => s.criteria_evaluation);
  const templateCompatible =
    !criteriaRequired || !!selected?.layout.criteria_heading;
  const locked = busy || !!pending;
  useEffect(() => {
    const lifecycle = epoch;
    return () => {
      lifecycle.current++;
    };
  }, []);
  const revoke = () => setConfirmed(false);
  async function operation(task: (current: () => boolean) => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(true);
    setError(false);
    revoke();
    try {
      await task(() => token === epoch.current);
    } catch {
      if (token === epoch.current) setError(true);
    } finally {
      lock.current = false;
      if (token === epoch.current) setBusy(false);
    }
  }
  function validateArchive(
    result: ReportArchive,
    id: string,
    receipt?: PendingArchive,
  ) {
    if (
      result.schema !== "qa-project-report-archive.v1" ||
      result.scope !== "immutable_qa_report_draft" ||
      result.id !== id ||
      result.project_id !== projectId ||
      result.acceptance !== "not_approved"
    )
      throw new Error("Invalid receipt");
    if (receipt) {
      const request = receipt.request;
      const refs = (items: { run_id: string; summary_hash: string }[]) =>
        items
          .map((i) => i.run_id + ":" + i.summary_hash)
          .sort()
          .join("|");
      if (
        result.title !== request.title ||
        result.template.id !== request.template_id ||
        result.template.version !== request.template_version ||
        result.supersedes_id !== request.supersedes_id ||
        refs(result.components) !== refs(request.sources)
      )
        throw new Error("Mismatched receipt");
    }
  }
  function showReceipt(result: ReportArchive) {
    setOpened(result);
    setPending(null);
    onPending(null);
    const metadata: ArchiveMetadata = {
      id: result.id,
      project_id: result.project_id,
      root_id: result.root_id,
      revision: result.revision,
      supersedes_id: result.supersedes_id,
      title: result.title,
      template_id: result.template.id,
      template_version: result.template.version,
      created_at_ms: result.created_at_ms,
    };
    setHistory((old) => [metadata, ...old.filter((r) => r.id !== result.id)]);
    setStaged([]);
    setSummary(null);
    setParent(null);
  }
  function load() {
    if (pending) return;
    setRuns([]);
    setTemplates([]);
    setHistory([]);
    setStaged([]);
    setSummary(null);
    setRunId("");
    setTemplateKey("");
    setParent(null);
    void operation(async (current) => {
      const [r, t, h] = await Promise.all([
        evaluationApi<{ runs: ReviewRun[] }>(base + "/review-runs"),
        evaluationApi<{ templates: ArchiveTemplate[] }>(
          base + "/report-templates",
        ),
        evaluationApi<{ archives: ArchiveMetadata[] }>(
          base + "/report-archives",
        ),
      ]);
      if (!current()) return;
      setRuns(r.runs);
      setTemplates(t.templates);
      setHistory(h.archives);
      const first =
        t.templates.find((item) => item.language === (zh ? "zh" : "en")) ??
        t.templates[0];
      setTemplateKey(first ? first.id + "@" + first.version : "");
    });
  }
  function verify() {
    if (!runId || pending) return;
    setSummary(null);
    void operation(async (current) => {
      const result = await evaluationApi<ReviewSummary>(
        base + "/review-runs/" + encodeURIComponent(runId) + "/summary",
      );
      if (
        result.schema !== "qa-human-summary.v1" ||
        result.scope !== "verified_human_summary_preview" ||
        result.project_id !== projectId ||
        result.run_id !== runId ||
        result.acceptance !== "not_approved"
      )
        throw new Error("Invalid summary");
      if (current()) setSummary(result);
    });
  }
  function archive() {
    if (
      !confirmed ||
      !selected ||
      !templateCompatible ||
      !title.trim() ||
      !staged.length ||
      pending ||
      lock.current
    )
      return;
    const receipt: PendingArchive = {
      id: crypto.randomUUID().replaceAll("-", ""),
      request: {
        title: title.trim(),
        template_id: selected.id,
        template_version: selected.version,
        sources: staged.map((s) => ({
          run_id: s.run_id,
          summary_hash: s.summary_hash,
        })),
        supersedes_id: parent?.id ?? null,
        confirmed: true,
      },
    };
    setPending(receipt);
    onPending(receipt);
    void operation(async (current) => {
      const result = await evaluationApi<ReportArchive>(
        base + "/report-archives/" + receipt.id,
        receipt.request,
        "PUT",
      );
      validateArchive(result, receipt.id, receipt);
      if (current()) showReceipt(result);
    });
  }
  function reconcile() {
    if (!pending) return;
    const receipt = pending;
    void operation(async (current) => {
      const result = await evaluationApi<ReportArchive>(
        base + "/report-archives/" + receipt.id,
      );
      validateArchive(result, receipt.id, receipt);
      if (current()) showReceipt(result);
    });
  }
  const eligible =
    summary?.readiness === "review_complete" &&
    !summary.blockers.length &&
    staged.length < 10 &&
    !staged.some((s) => s.component_id === summary.component_id);
  function saveDocument(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    try {
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  function download() {
    if (!opened) return;
    saveDocument(
      new Blob([opened.markdown], { type: "text/markdown;charset=utf-8" }),
      `qa-report-${opened.id}-r${opened.revision}.md`,
    );
  }
  async function downloadWord() {
    if (!opened || locked) return;
    const archive = opened;
    await operation(async (current) => {
      const blob = await evaluationReportDocx(
        `${base}/report-archives/${archive.id}/exports/qa-docx-v1?archive_hash=${archive.archive_hash}`,
      );
      if (current())
        saveDocument(blob, `qa-report-${archive.id}-r${archive.revision}.docx`);
    });
  }
  return (
    <div className="min-w-0 space-y-4">
      <Button type="button" variant="outline" disabled={locked} onClick={load}>
        {zh ? "加载运行、模板和历史存档" : "Load runs, templates and archives"}
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {zh
            ? "操作未确认。请核对权限、密钥、完整复核或并发变更。写入不自动重试；如有待核对标识，只读取同一标识的收据。"
            : "Operation unconfirmed. Check permissions, key, complete review or concurrent changes. Writes never automatically retry; reconcile only the same pending ID."}
        </p>
      )}
      {pending && (
        <div className="space-y-2 rounded-md border p-3 text-sm">
          <p>
            {zh
              ? "待核对写入标识（离开页面前请保留，不要重新提交）："
              : "Pending write ID (keep before leaving this page; do not resubmit):"}{" "}
            <code className="break-all">{pending.id}</code>
          </p>
          <Button type="button" disabled={busy} onClick={reconcile}>
            {zh ? "核对待定存档收据" : "Check pending archive receipt"}
          </Button>
        </div>
      )}
      <fieldset disabled={locked} className="min-w-0 space-y-4">
        <label className="block space-y-1 text-sm">
          {zh ? "证据运行" : "Evidence run"}
          <select
            aria-label={zh ? "证据运行" : "Evidence run"}
            className={selectClass}
            value={runId}
            onChange={(e) => {
              setRunId(e.target.value);
              setSummary(null);
              revoke();
            }}
          >
            <option value="">
              {zh ? "选择效果运行" : "Choose effectiveness run"}
            </option>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.component_name} · {r.plan_label} · {r.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <Button
          type="button"
          variant="outline"
          disabled={!runId}
          onClick={verify}
        >
          {zh ? "验证所选汇总" : "Verify selected summary"}
        </Button>
        {summary && (
          <div className="space-y-2 rounded-md border p-3 text-sm">
            <p>
              {summary.component_name} · {summary.plan_label} ·{" "}
              {summary.human_pass_rate.numerator} /{" "}
              {summary.human_pass_rate.denominator} (
              {(summary.human_pass_rate.value * 100).toFixed(2)}%)
            </p>
            <p>
              {summary.readiness === "review_complete" &&
              !summary.blockers.length
                ? zh
                  ? "复核完整，不等于验收通过"
                  : "Review complete, not acceptance"
                : zh
                  ? "复核不完整：请返回人工复核处理，不能存档。"
                  : "Review incomplete: return to human review before archiving."}
            </p>
            <EvaluationCriteriaView
              assessment={summary.criteria_evaluation}
              zh={zh}
            />
            <code className="block break-all">{summary.summary_hash}</code>
            <Button
              type="button"
              variant="outline"
              disabled={!eligible}
              onClick={() => {
                if (!eligible) return;
                setStaged((old) => [...old, summary]);
                setSummary(null);
                revoke();
              }}
            >
              {zh ? "添加已验证组件" : "Add verified component"}
            </Button>
          </div>
        )}
        <ul
          aria-label={zh ? "报告组件" : "Report components"}
          className="space-y-2"
        >
          {staged.map((s) => (
            <li
              key={s.component_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm"
            >
              <span>
                {s.component_name} · {s.human_pass_rate.numerator} /{" "}
                {s.human_pass_rate.denominator} (
                {(s.human_pass_rate.value * 100).toFixed(2)}%)
              </span>
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setStaged((old) =>
                    old.filter((item) => item.component_id !== s.component_id),
                  );
                  revoke();
                }}
              >
                {zh ? "移除" : "Remove"} {s.component_name}
              </Button>
            </li>
          ))}
        </ul>
        <div className="grid min-w-0 gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm">
            {zh ? "存档标题" : "Archive title"}
            <Input
              value={title}
              maxLength={160}
              onChange={(e) => {
                setTitle(e.target.value);
                revoke();
              }}
            />
          </label>
          <label className="min-w-0 space-y-1 text-sm">
            {zh ? "存档模板" : "Archive template"}
            <select
              aria-label={zh ? "存档模板" : "Archive template"}
              className={selectClass}
              value={templateKey}
              onChange={(e) => {
                setTemplateKey(e.target.value);
                revoke();
              }}
            >
              {templates.map((t) => (
                <option
                  key={t.id + "@" + t.version}
                  value={t.id + "@" + t.version}
                  disabled={criteriaRequired && !t.layout.criteria_heading}
                >
                  {t.language} · {t.id}@{t.version}
                </option>
              ))}
            </select>
          </label>
        </div>
        {!templateCompatible && (
          <p role="status" className="text-sm">
            {zh
              ? "请选择包含冻结效果标准的模板（1.1.0）；旧模板仍可用于旧计划和历史存档。"
              : "Choose a template that includes frozen effectiveness criteria (1.1.0); older templates remain available for legacy plans and archives."}
          </p>
        )}
        {parent && (
          <p className="text-sm break-all">
            {zh ? "新修订源于：" : "New revision of: "}
            {parent.title} · {parent.id}
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setParent(null);
                revoke();
              }}
            >
              {zh ? "取消修订" : "Clear revision parent"}
            </Button>
          </p>
        )}
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={confirmed}
            aria-label={
              zh ? "确认不可变草稿存档" : "Confirm immutable draft storage"
            }
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          {zh
            ? "我已核对各组件来源，同意服务器重新验证并冻结模板与结果。后续修改只创建新版本，不会自动批准或出具正式报告。"
            : "I checked each source and consent to server reverification and freezing templates/results. Changes create new revisions, never automatic approval or formal publication."}
        </label>
        <Button
          type="button"
          disabled={
            !confirmed ||
            !selected ||
            !templateCompatible ||
            !title.trim() ||
            !staged.length
          }
          onClick={archive}
        >
          {zh ? "存档已验证草稿" : "Archive verified draft"}
        </Button>
      </fieldset>
      <div className="space-y-2">
        <h3 className="font-semibold">
          {zh ? "历史存档（最近 100 条）" : "Historical archives (latest 100)"}
        </h3>
        {history.map((item) => (
          <Button
            key={item.id}
            type="button"
            variant="outline"
            className="h-auto max-w-full justify-start text-left break-words whitespace-normal"
            disabled={locked}
            onClick={() => {
              setOpened(null);
              void operation(async (current) => {
                const result = await evaluationApi<ReportArchive>(
                  base + "/report-archives/" + item.id,
                );
                validateArchive(result, item.id);
                if (current()) setOpened(result);
              });
            }}
          >
            {zh ? "打开" : "Open"} {item.title} · r{item.revision} ·{" "}
            {item.id.slice(0, 8)}
          </Button>
        ))}
      </div>
      {opened && (
        <section
          data-testid="archive-document"
          aria-label={zh ? "不可变报告详情" : "Immutable report detail"}
          className="min-w-0 space-y-3 rounded-md border p-3"
        >
          <h3 className="font-semibold">
            {zh ? "历史草稿 · 修订" : "Historical draft · Revision"}{" "}
            {opened.revision} · {zh ? "未批准" : "Not approved"}
          </h3>
          <p className="text-xs break-all">
            {opened.template.id}@{opened.template.version} · {opened.id}
          </p>
          <p className="text-xs break-all">
            {zh ? "存档哈希：" : "Archive hash: "}
            {opened.archive_hash}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" onClick={download}>
              {zh ? "下载已存档 Markdown" : "Download archived Markdown"}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={locked}
              onClick={() => void downloadWord()}
            >
              {zh ? "下载 Word 草稿" : "Download Word draft"}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={locked}
              onClick={() => {
                setParent(opened);
                setTitle(opened.title);
                revoke();
              }}
            >
              {zh ? "作为修订来源" : "Use as revision parent"}
            </Button>
          </div>
          <pre className="bg-muted max-h-[32rem] overflow-auto rounded-md p-3 text-sm break-words whitespace-pre-wrap">
            {opened.markdown}
          </pre>
        </section>
      )}
    </div>
  );
}
