"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { IndependentArchivePanel } from "@/components/workspace/independent-archive-panel";
import { ProjectReportPanel } from "@/components/workspace/project-report-panel";
import { VerifiedProjectReportPanel } from "@/components/workspace/verified-project-report-panel";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  downloadReport,
  fetchReportTemplates,
  fetchReportAssistantStatus,
  requestReportAdvice,
  generateReportPreview,
} from "@/core/reports/api";
import {
  emptyReportForm,
  toReportFacts,
  type ReportForm,
} from "@/core/reports/form";
import { enReports, zhReports } from "@/core/reports/messages";
import {
  effectFields,
  measurementFields,
  metadataFields,
  narrativeFields,
  performanceCountFields,
  sampleFields,
  type NumericField,
  type ReportPreview,
  type ReportAssistantResult,
  type ReportAssistantStatus,
  type ReportTemplateSummary,
} from "@/core/reports/types";

const selectClass =
  "border-input bg-background w-full rounded-md border p-2 text-sm";
const templateKey = (template: ReportTemplateSummary) =>
  `${template.id}@${template.version}`;

export default function ReportsPage() {
  const { locale } = useI18n();
  const m = locale === "zh-CN" ? zhReports : enReports;
  const requestRevision = useRef(0);
  const [form, setForm] = useState<ReportForm>(emptyReportForm);
  const [templates, setTemplates] = useState<ReportTemplateSummary[]>([]);
  const [selection, setSelection] = useState("");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [agentStatus, setAgentStatus] = useState<ReportAssistantStatus | null>(
    null,
  );
  const [advice, setAdvice] = useState<ReportAssistantResult | null>(null);
  const [consent, setConsent] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const selected = templates.find(
    (template) => templateKey(template) === selection,
  );

  useEffect(() => {
    let active = true;
    requestRevision.current += 1;
    setRunning(false);
    setLoading(true);
    setPreview(null);
    setError(null);
    setTemplates([]);
    setAgentStatus(null);
    setAdvice(null);
    setConsent(false);
    setConfirmed(false);
    void fetchReportAssistantStatus()
      .then((status) => {
        if (active) setAgentStatus(status);
      })
      .catch(() => {
        if (active)
          setAgentStatus({ available: false, reason: "status_failed" });
      });
    void fetchReportTemplates()
      .then((items) => {
        if (!active) return;
        setTemplates(items);
        const preferred =
          items.find(
            (template) =>
              template.language === (locale === "zh-CN" ? "zh" : "en"),
          ) ?? items[0];
        setSelection(preferred ? templateKey(preferred) : "");
      })
      .catch((cause: unknown) => {
        if (active)
          setError(
            cause instanceof Error ? cause.message : "Unable to load templates",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      requestRevision.current += 1;
    };
  }, [locale, reload]);

  function invalidate() {
    requestRevision.current += 1;
    setPreview(null);
    setAdvice(null);
    setConsent(false);
    setConfirmed(false);
    setError(null);
  }

  async function askAgent() {
    if (!selected || running || !consent || !agentStatus?.available) return;
    let facts;
    try {
      facts = toReportFacts(form);
    } catch {
      setError(m.invalid);
      return;
    }
    const revision = ++requestRevision.current;
    setRunning(true);
    setConsent(false);
    setPreview(null);
    setAdvice(null);
    setConfirmed(false);
    setError(null);
    try {
      const result = await requestReportAdvice(selected, facts);
      if (requestRevision.current === revision) setAdvice(result);
    } catch (cause) {
      if (requestRevision.current === revision)
        setError(cause instanceof Error ? cause.message : m.invalid);
    } finally {
      if (requestRevision.current === revision) setRunning(false);
    }
  }

  function update<K extends keyof ReportForm>(key: K, value: ReportForm[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
    invalidate();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || running) return;
    setPreview(null);
    setError(null);
    let facts;
    try {
      facts = toReportFacts(form);
    } catch {
      setError(m.invalid);
      return;
    }
    const revision = ++requestRevision.current;
    setRunning(true);
    try {
      const attachment =
        advice && confirmed
          ? {
              ...advice.advice,
              model_name: advice.model_name,
              facts_sha256: advice.facts_sha256,
              template_id: advice.template_id,
              template_version: advice.template_version,
              human_confirmed: true as const,
            }
          : undefined;
      const result = await generateReportPreview(selected, facts, attachment);
      if (requestRevision.current === revision) setPreview(result);
    } catch (cause) {
      if (requestRevision.current === revision)
        setError(cause instanceof Error ? cause.message : m.invalid);
    } finally {
      if (requestRevision.current === revision) setRunning(false);
    }
  }

  function numberField(key: NumericField, required: boolean) {
    const isTTFT = key.startsWith("ttft_");
    return (
      <label key={key} className="grid gap-1 text-sm" htmlFor={`report-${key}`}>
        {m.labels[key]}
        <Input
          id={`report-${key}`}
          data-testid={`report-${key}`}
          type="number"
          min="0"
          step={
            measurementFields.includes(
              key as (typeof measurementFields)[number],
            )
              ? "any"
              : "1"
          }
          required={required}
          disabled={isTTFT && !form.content_streaming}
          value={form[key]}
          onChange={(event) => update(key, event.target.value)}
        />
      </label>
    );
  }

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="w-full max-w-5xl space-y-6 p-4 md:p-8">
          <h1 className="text-2xl font-semibold">{m.title}</h1>
          <p
            data-testid="report-notice"
            className="rounded-lg border border-amber-500/50 bg-amber-500/10 p-4 text-sm"
          >
            {m.notice}
          </p>
          <p className="text-muted-foreground text-sm">{m.help}</p>
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          {loading && <p role="status">{m.loading}</p>}
          {!loading && !templates.length && (
            <div className="space-y-2">
              {!error && <p role="alert">{m.empty}</p>}
              <Button
                variant="outline"
                onClick={() => setReload((value) => value + 1)}
              >
                {m.retry}
              </Button>
            </div>
          )}
          <IndependentArchivePanel kind="report" zh={locale === "zh-CN"} />
          <VerifiedProjectReportPanel zh={locale === "zh-CN"} />
          <ProjectReportPanel
            getFacts={() => toReportFacts(form)}
            applyProposal={(proposal) => {
              invalidate();
              setForm((current) => ({
                ...current,
                ...(proposal.title ? { title: proposal.title } : {}),
                ...(proposal.project_name
                  ? { project_name: proposal.project_name }
                  : {}),
                ...(proposal.components[0]
                  ? {
                      component_name: proposal.components[0].name,
                      component_version: proposal.components[0].version,
                    }
                  : {}),
              }));
            }}
          />
          <form onSubmit={submit} autoComplete="off">
            <fieldset
              disabled={running || loading || !selected}
              className="space-y-6 disabled:opacity-60"
            >
              <label className="grid gap-1 text-sm" htmlFor="report-template">
                {m.template}
                <select
                  id="report-template"
                  className={selectClass}
                  value={selection}
                  onChange={(event) => {
                    setSelection(event.target.value);
                    invalidate();
                  }}
                >
                  {templates.map((template) => (
                    <option
                      key={templateKey(template)}
                      value={templateKey(template)}
                    >
                      {template.name} · {template.language} · v
                      {template.version}
                    </option>
                  ))}
                </select>
              </label>
              <section className="space-y-3 rounded-lg border p-4">
                <h2 className="font-semibold">{m.metadata}</h2>
                <div className="grid gap-4 md:grid-cols-2">
                  {metadataFields.map((key) => (
                    <label
                      key={key}
                      className="grid gap-1 text-sm"
                      htmlFor={`report-${key}`}
                    >
                      {m.labels[key]}
                      <Input
                        id={`report-${key}`}
                        data-testid={`report-${key}`}
                        maxLength={200}
                        required
                        value={form[key]}
                        onChange={(event) => update(key, event.target.value)}
                      />
                    </label>
                  ))}
                  <label className="grid gap-1 text-sm" htmlFor="report-mode">
                    {m.mode}
                    <select
                      id="report-mode"
                      className={selectClass}
                      value={form.evaluation_mode}
                      onChange={(event) =>
                        update(
                          "evaluation_mode",
                          event.target.value as ReportForm["evaluation_mode"],
                        )
                      }
                    >
                      <option value="BASELINE">{m.baseline}</option>
                      <option value="ACCEPTANCE">{m.acceptance}</option>
                    </select>
                  </label>
                </div>
              </section>
              <section className="space-y-3 rounded-lg border p-4">
                <label className="flex items-center gap-2 font-semibold">
                  <input
                    type="checkbox"
                    checked={form.includeEffect}
                    onChange={(event) =>
                      update("includeEffect", event.target.checked)
                    }
                  />
                  {m.effect}
                </label>
                {form.includeEffect && (
                  <div className="grid gap-4 sm:grid-cols-3">
                    {effectFields.map((key) => numberField(key, true))}
                  </div>
                )}
              </section>
              <section className="space-y-3 rounded-lg border p-4">
                <label className="flex items-center gap-2 font-semibold">
                  <input
                    type="checkbox"
                    checked={form.includePerformance}
                    onChange={(event) =>
                      update("includePerformance", event.target.checked)
                    }
                  />
                  {m.performance}
                </label>
                {form.includePerformance && (
                  <div className="space-y-4">
                    <div className="grid gap-4 sm:grid-cols-3">
                      {performanceCountFields.map((key) =>
                        numberField(key, true),
                      )}
                    </div>
                    <label
                      className="grid gap-1 text-sm"
                      htmlFor="report-population"
                    >
                      {m.population}
                      <select
                        id="report-population"
                        className={selectClass}
                        value={form.metric_population}
                        onChange={(event) =>
                          update(
                            "metric_population",
                            event.target
                              .value as ReportForm["metric_population"],
                          )
                        }
                      >
                        <option value="successful_requests">
                          successful_requests
                        </option>
                        <option value="all_attempts">all_attempts</option>
                        <option value="failed_attempts">failed_attempts</option>
                      </select>
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={form.content_streaming}
                        onChange={(event) => {
                          update("content_streaming", event.target.checked);
                          if (!event.target.checked)
                            setForm((previous) => ({
                              ...previous,
                              ttft_mean_ms: "",
                              ttft_sample_count: "",
                            }));
                        }}
                      />
                      {m.streaming}
                    </label>
                    <div className="grid gap-4 sm:grid-cols-2">
                      {[...measurementFields, ...sampleFields].map((key) =>
                        numberField(key, false),
                      )}
                    </div>
                    <label
                      className="grid gap-1 text-sm"
                      htmlFor="report-token-source"
                    >
                      {m.tokenSource}
                      <select
                        id="report-token-source"
                        className={selectClass}
                        value={form.token_source}
                        onChange={(event) =>
                          update(
                            "token_source",
                            event.target.value as ReportForm["token_source"],
                          )
                        }
                      >
                        {[
                          "unavailable",
                          "provider_usage",
                          "tokenizer",
                          "estimate",
                        ].map((value) => (
                          <option key={value}>{value}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                )}
              </section>
              <section className="space-y-3 rounded-lg border p-4">
                <h2 className="font-semibold">{m.narrative}</h2>
                {narrativeFields.map((key) => (
                  <label
                    key={key}
                    className="grid gap-1 text-sm"
                    htmlFor={`report-${key}`}
                  >
                    {m.labels[key]}
                    <Textarea
                      id={`report-${key}`}
                      data-testid={`report-${key}`}
                      maxLength={2000}
                      required
                      value={form[key]}
                      onChange={(event) => update(key, event.target.value)}
                    />
                  </label>
                ))}
              </section>
              <section
                className="space-y-3 rounded-lg border p-4"
                aria-label={m.assistant.title}
              >
                <h2 className="font-semibold">{m.assistant.title}</h2>
                <p className="text-sm">{m.assistant.notice}</p>
                {!agentStatus?.available ? (
                  <p role="status" className="text-muted-foreground text-sm">
                    {m.assistant.unavailable}
                  </p>
                ) : (
                  <>
                    <p className="text-sm">{agentStatus.model_name}</p>
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        data-testid="report-agent-consent"
                        type="checkbox"
                        checked={consent}
                        onChange={(event) => setConsent(event.target.checked)}
                      />
                      {m.assistant.consent}
                    </label>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={!consent}
                      onClick={() => void askAgent()}
                    >
                      {m.assistant.request}
                    </Button>
                  </>
                )}
                {advice && (
                  <div
                    data-testid="report-agent-advice"
                    className="space-y-3 text-sm"
                  >
                    <h3 className="font-semibold">{m.assistant.summary}</h3>
                    <p className="whitespace-pre-wrap">
                      {advice.advice.summary}
                    </p>
                    {(["findings", "recommendations"] as const).map((key) => (
                      <div key={key}>
                        <h3 className="font-semibold">{m.assistant[key]}</h3>
                        <ul className="list-disc pl-5">
                          {advice.advice[key].map((item, index) => (
                            <li key={index} className="whitespace-pre-wrap">
                              {item}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                    <label className="flex items-start gap-2">
                      <input
                        data-testid="report-agent-confirm"
                        type="checkbox"
                        checked={confirmed}
                        onChange={(event) => {
                          setConfirmed(event.target.checked);
                          setPreview(null);
                        }}
                      />
                      {m.assistant.confirm}
                    </label>
                  </div>
                )}
              </section>
              <Button type="submit">
                {running ? m.generating : m.generate}
              </Button>
            </fieldset>
          </form>
          {preview && (
            <section className="space-y-3" aria-label={m.preview}>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={() => downloadReport(preview, "md")}
                >
                  {m.downloadMd}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => downloadReport(preview, "json")}
                >
                  {m.downloadJson}
                </Button>
              </div>
              <pre
                data-testid="report-preview"
                className="bg-muted overflow-x-auto rounded-lg p-4 text-sm break-words whitespace-pre-wrap"
              >
                {preview.markdown}
              </pre>
            </section>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
