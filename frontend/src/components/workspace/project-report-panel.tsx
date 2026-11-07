"use client";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { evaluationApi } from "@/core/evaluation/api";
import { useI18n } from "@/core/i18n/hooks";
import type { ReportFacts, ReportTemplateSummary } from "@/core/reports/types";

interface Proposal {
  title: string;
  project_name: string;
  components: { name: string; version: string }[];
  questions: string[];
}
interface IntakeTurn {
  message: string;
  proposal: Proposal;
}
interface ProjectPreview {
  markdown: string;
  manifest: { template_version: string; facts_sha256: string };
}

export function ProjectReportPanel({
  getFacts,
  applyProposal,
}: {
  getFacts: () => ReportFacts;
  applyProposal: (proposal: Proposal) => void;
}) {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const [components, setComponents] = useState<ReportFacts[]>([]);
  const [templates, setTemplates] = useState<ReportTemplateSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [preview, setPreview] = useState<ProjectPreview | null>(null);
  const [requirements, setRequirements] = useState("");
  const [history, setHistory] = useState<IntakeTurn[]>([]);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const revision = useRef(0);
  useEffect(() => {
    let active = true;
    revision.current++;
    setPreview(null);
    setProposal(null);
    setHistory([]);
    setRequirements("");
    setConsent(false);
    setBusy(false);
    void evaluationApi<{ templates: ReportTemplateSummary[] }>(
      "reports/project/templates",
    )
      .then((data) => {
        if (!active) return;
        setTemplates(data.templates);
        const t = data.templates.find((t) => t.language === (zh ? "zh" : "en"));
        setSelected(t ? t.id + "@" + t.version : "");
      })
      .catch(() => {
        if (active)
          setError(zh ? "无法加载项目模板" : "Cannot load project templates");
      });
    return () => {
      active = false;
    };
  }, [zh]);
  const invalidate = () => {
    revision.current++;
    setPreview(null);
    setError("");
  };
  function add() {
    try {
      const facts = getFacts();
      if (
        components.some(
          (c) =>
            c.component_name === facts.component_name &&
            c.component_version === facts.component_version,
        )
      )
        throw new Error(
          zh
            ? "该组件版本已加入，请先移除旧快照。"
            : "Component/version already staged; remove the old snapshot first.",
        );
      if (components.length >= 30) throw new Error("Maximum 30 components");
      setComponents([...components, facts]);
      invalidate();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Complete component fields first",
      );
    }
  }
  async function generate() {
    const t = templates.find((t) => t.id + "@" + t.version === selected);
    if (!t) return;
    const seq = ++revision.current;
    setBusy(true);
    setError("");
    setPreview(null);
    try {
      const result = await evaluationApi<ProjectPreview>(
        "reports/project/preview",
        { template_id: t.id, template_version: t.version, components },
      );
      if (seq === revision.current) setPreview(result);
    } catch (e) {
      if (seq === revision.current)
        setError(e instanceof Error ? e.message : "Generate failed");
    } finally {
      if (seq === revision.current) setBusy(false);
    }
  }
  async function ask() {
    if (!consent || !requirements.trim() || history.length >= 10) return;
    const message = requirements.trim();
    if (JSON.stringify({ message, history }).length > 24000) {
      setError(
        zh
          ? "对话超过 24000 字符，请开始新对话。"
          : "Conversation exceeds 24000 characters. Start a new conversation.",
      );
      return;
    }
    const seq = ++revision.current;
    setBusy(true);
    setError("");
    setProposal(null);
    setConsent(false);
    try {
      const result = await evaluationApi<{ proposal: Proposal }>(
        "reports/project/intake",
        { message, history, language: zh ? "zh" : "en", consent: true },
      );
      if (seq === revision.current) {
        setProposal(result.proposal);
        setHistory([...history, { message, proposal: result.proposal }]);
        setRequirements("");
      }
    } catch (e) {
      if (seq === revision.current)
        setError(e instanceof Error ? e.message : "Assistant unavailable");
    } finally {
      if (seq === revision.current) setBusy(false);
    }
  }
  function download(format: "md" | "json") {
    if (!preview) return;
    const url = URL.createObjectURL(
      new Blob(
        [format === "md" ? preview.markdown : JSON.stringify(preview, null, 2)],
        {
          type:
            format === "md"
              ? "text/markdown;charset=utf-8"
              : "application/json",
        },
      ),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "project-evaluation-draft." + format;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <section className="mb-6 space-y-4 rounded-xl border p-4">
      <h2 className="text-lg font-semibold">
        {zh
          ? "项目报告 · 多组件与需求助手"
          : "Project report · Multiple components & requirements assistant"}
      </h2>
      <p className="text-muted-foreground text-sm">
        {zh
          ? "模板参考本地报告的通用章节结构，未包含真实项目和历史数据。先让助手整理需求，确认字段后在下方填写各组件结果；逐个加入快照，再统一生成。当前为未核验草稿，支持 Markdown / JSON，尚未复刻原 DOCX 的版式。"
          : "Sanitized templates follow the reference reports’ section structure, without customer content. Confirm assistant fields, fill each component below, stage snapshots, then generate one project draft. Markdown / JSON only; original DOCX styling is not reproduced yet."}
      </p>
      <fieldset disabled={busy} className="space-y-3">
        <div className="bg-muted/20 rounded-xl border p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold">
              {zh ? "报告需求对话" : "Report requirements conversation"}
            </h3>
            <span className="text-muted-foreground text-xs">
              {history.length} / 10 {zh ? "轮" : "rounds"}
            </span>
            <Button
              type="button"
              variant="ghost"
              disabled={busy || history.length === 0}
              onClick={() => {
                revision.current++;
                setHistory([]);
                setRequirements("");
                setProposal(null);
                setConsent(false);
                setError("");
              }}
            >
              {zh ? "开始新对话" : "Start new conversation"}
            </Button>
          </div>
          <p className="text-muted-foreground mt-2 text-xs leading-5">
            {zh
              ? "可逐轮补充和修正，助手会参考本次对话的前文。最多 10 轮、合计 24000 字符；仅当前页面内存，离开不恢复。前文建议未经核实，确认字段不会修改实测指标。"
              : "Add or correct details over multiple turns. Up to 10 rounds and 24000 characters, held in page memory only; not resumable after leaving. Earlier suggestions are unverified; confirming fields never changes measured metrics."}
          </p>
          <div
            role="log"
            aria-label={zh ? "需求对话记录" : "Requirements conversation"}
            aria-live="polite"
            className="mt-4 max-h-80 space-y-4 overflow-y-auto"
          >
            {history.length === 0 && (
              <p className="text-muted-foreground text-sm">
                {zh
                  ? "描述你的项目与组件，助手会列出待确认的问题。"
                  : "Describe your project and components; the assistant will ask for missing details."}
              </p>
            )}
            {history.map((turn, index) => (
              <article key={index} className="space-y-3 text-sm">
                <div className="bg-primary/10 ml-6 rounded-xl p-3">
                  <p className="mb-1 font-medium">
                    {zh ? "你" : "You"} · {index + 1}
                  </p>
                  <p className="break-words whitespace-pre-wrap">
                    {turn.message}
                  </p>
                </div>
                <div className="bg-background mr-6 rounded-xl border p-3">
                  <p className="mb-2 font-medium">
                    {zh
                      ? "报告助手 · 待确认"
                      : "Report assistant · Unconfirmed"}
                  </p>
                  <p>
                    {turn.proposal.title} {turn.proposal.project_name}
                  </p>
                  <ul className="my-2 list-inside list-disc">
                    {turn.proposal.components.map((component, i) => (
                      <li key={i}>
                        {component.name} {component.version}
                      </li>
                    ))}
                  </ul>
                  <ol className="list-inside list-decimal space-y-1">
                    {turn.proposal.questions.map((question, i) => (
                      <li key={i}>{question}</li>
                    ))}
                  </ol>
                </div>
              </article>
            ))}
          </div>
        </div>
        <label className="block text-sm">
          {zh ? "告诉报告助手你的需求" : "Describe report requirements"}
          <Textarea
            maxLength={4000}
            value={requirements}
            onChange={(e) => {
              setRequirements(e.target.value);
              setProposal(null);
              setConsent(false);
            }}
            placeholder={
              zh
                ? "例如：我需要一个包含多个问答与图像组件的测试报告，请先列出需要确认的字段。请不要粘贴凭据或原始客户报告。"
                : "Describe components and the report you need. Do not paste credentials or raw customer reports."
            }
          />
        </label>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          {zh
            ? "同意将本轮需求和上方全部对话记录发送给已配置的报告模型（可能含你主动填写的名称）。不会自动附带本地文件、已录入指标或其他材料；每轮需重新同意。"
            : "Authorize sending only the requirements and conversation history above to the configured report model, including names you enter. No files, entered metrics or other materials are attached automatically. Consent is required each turn."}
        </label>
        <Button
          disabled={
            !consent || !requirements.trim() || busy || history.length >= 10
          }
          onClick={() => void ask()}
        >
          {history.length > 0
            ? zh
              ? "继续对话"
              : "Continue conversation"
            : zh
              ? "整理需求 / 追问关键字段"
              : "Extract fields / ask missing details"}
        </Button>
        {proposal && (
          <div className="space-y-2 rounded border p-3">
            <strong>
              {zh
                ? "AI 建议（待确认，不是测试事实）"
                : "AI suggestions (unconfirmed, not test facts)"}
            </strong>
            <p className="text-sm">
              {proposal.title} · {proposal.project_name}
            </p>
            <p className="text-muted-foreground text-xs">
              {zh
                ? "先填入项目及首个组件，再逐个确认其他组件。计数、性能数据和证据必须在事实表单中填写。"
                : "Fill the shared project and first component, then confirm remaining components. Enter counters, performance and evidence in the facts form."}
            </p>
            <Button
              variant="outline"
              onClick={() => {
                applyProposal(proposal);
                setProposal(null);
              }}
            >
              {zh
                ? "确认采用项目字段（不改指标）"
                : "Confirm project fields (leave metrics unchanged)"}
            </Button>
          </div>
        )}
        <hr />
        <h3 className="font-semibold">
          {zh ? "已确认的组件快照" : "Confirmed component snapshots"}
        </h3>
        <Button variant="outline" onClick={add}>
          {zh
            ? "将下方填写的组件结果加入项目"
            : "Stage component results from the form below"}
        </Button>
        <p className="text-muted-foreground text-xs">
          {zh
            ? "快照不随下方表单变化。修改后请移除旧快照再添加；同项目、测试人、周期、评测模式必须一致。仅保存在当前页面内存，离开将丢失。"
            : "Snapshots do not change with the form. Remove and restage after edits. Shared project, tester, period and mode must match. Page memory only; leaving loses drafts."}
        </p>
        <ul className="space-y-2">
          {components.map((c, i) => (
            <li
              key={c.component_name + c.component_version}
              className="flex justify-between gap-2 rounded border p-2 text-sm"
            >
              <span>
                {i + 1}. {c.project_name} / {c.component_name} /{" "}
                {c.component_version}
              </span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setComponents(components.filter((_, n) => n !== i));
                  invalidate();
                }}
              >
                {zh ? "移除" : "Remove"}
              </Button>
            </li>
          ))}
        </ul>
        <label className="block text-sm">
          {zh
            ? "项目报告模板（固定版本）"
            : "Project template (pinned version)"}
          <select
            className="mt-1 block w-full rounded border p-2"
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              invalidate();
            }}
          >
            {templates
              .filter((t) => t.language === (zh ? "zh" : "en"))
              .map((t) => (
                <option key={t.id + t.version} value={t.id + "@" + t.version}>
                  {t.name} · {t.version}
                </option>
              ))}
          </select>
        </label>
        <Button
          disabled={!components.length || !selected || busy}
          onClick={() => void generate()}
        >
          {zh ? "生成项目报告草稿" : "Generate project draft"}
        </Button>
      </fieldset>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {preview && (
        <div className="space-y-2">
          <Button variant="outline" onClick={() => download("md")}>
            {zh ? "下载项目 Markdown" : "Download project Markdown"}
          </Button>
          <Button
            variant="outline"
            className="ml-2"
            onClick={() => download("json")}
          >
            JSON
          </Button>
          <pre className="bg-muted max-h-[32rem] overflow-auto rounded p-4 text-sm whitespace-pre-wrap">
            {preview.markdown}
          </pre>
        </div>
      )}
    </section>
  );
}
