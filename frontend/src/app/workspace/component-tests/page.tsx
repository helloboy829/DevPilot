"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { RequestDebugger } from "@/components/workspace/request-debugger";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  useComponentRunReport,
  useComponentRuns,
  useComponents,
  useCreateComponent,
  useDeleteComponent,
  useTriggerComponentRun,
  useUpdateComponent,
} from "@/core/component-tests/hooks";
import type {
  ComponentTestRun,
  ComponentTestType,
} from "@/core/component-tests/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const NONE = "—";

const TRANSPORTS = [
  "openai_chat",
  "dify_chat",
  "dify_workflow",
  "http_post",
] as const;
const RESPONSE_MODES = ["blocking", "streaming"] as const;
const VALIDATION_TYPES = [
  "reference_text",
  "manual_review",
  "reference_values",
  "field_completeness",
  "structure",
] as const;

const DEFAULT_EFFECT_PARAMS = JSON.stringify({ samples: [] }, null, 2);
const DEFAULT_PERF_PARAMS = JSON.stringify(
  { payload: {}, max_requests: 20, concurrency_levels: [1, 5] },
  null,
  2,
);

function formatTimestamp(value: string | null, locale: string): string {
  if (!value) {
    return NONE;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const intlLocale = locale === "zh-CN" ? "zh-CN" : "en-US";
  return new Intl.DateTimeFormat(intlLocale, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function parseParams(
  text: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  try {
    const value = JSON.parse(text) as unknown;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      return { ok: true, value: value as Record<string, unknown> };
    }
    return { ok: false, error: "not-an-object" };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export default function ComponentTestsPage() {
  const { t, locale } = useI18n();
  const ct = t.componentTests;
  const componentsQuery = useComponents();
  const components = componentsQuery.data ?? [];

  const [statusFilter, setStatusFilter] = useState<
    "all" | "enabled" | "disabled"
  >("all");
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(
    null,
  );

  // Create form state.
  const [name, setName] = useState("");
  const [componentCode, setComponentCode] = useState("");
  const [transport, setTransport] = useState<string>("openai_chat");
  const [apiUrl, setApiUrl] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [responseMode, setResponseMode] = useState<string>("blocking");
  const [supportsStreaming, setSupportsStreaming] = useState(false);
  const [validationType, setValidationType] =
    useState<string>("reference_text");
  const [acceptanceCriteria, setAcceptanceCriteria] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  // Edit form state.
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editComponentCode, setEditComponentCode] = useState("");
  const [editTransport, setEditTransport] = useState<string>("openai_chat");
  const [editApiUrl, setEditApiUrl] = useState("");
  const [editApiToken, setEditApiToken] = useState("");
  const [editResponseMode, setEditResponseMode] = useState<string>("blocking");
  const [editSupportsStreaming, setEditSupportsStreaming] = useState(false);
  const [editValidationType, setEditValidationType] =
    useState<string>("reference_text");
  const [editAcceptanceCriteria, setEditAcceptanceCriteria] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  // Delete confirm dialog.
  const [deleteOpen, setDeleteOpen] = useState(false);

  // Run trigger dialog.
  const [runOpen, setRunOpen] = useState(false);
  const [runTestType, setRunTestType] = useState<ComponentTestType>("effect");
  const [runParams, setRunParams] = useState(DEFAULT_EFFECT_PARAMS);
  const [runParamsError, setRunParamsError] = useState<string | null>(null);

  // Report dialog.
  const [reportRunId, setReportRunId] = useState<string | null>(null);

  const filteredData = components.filter((component) => {
    if (statusFilter === "all") {
      return true;
    }
    if (statusFilter === "enabled") {
      return component.enabled;
    }
    return !component.enabled;
  });
  const selectedComponent =
    filteredData.find((component) => component.id === selectedComponentId) ??
    filteredData[0];
  const runsQuery = useComponentRuns(selectedComponent?.id);
  const runs = runsQuery.data ?? [];

  const reportQuery = useComponentRunReport(reportRunId);
  const createComponent = useCreateComponent();
  const updateComponent = useUpdateComponent(selectedComponent?.id ?? "");
  const deleteComponent = useDeleteComponent();
  const triggerRun = useTriggerComponentRun(selectedComponent?.id ?? "");

  const transportLabel = (v: string) =>
    (ct.transports as Record<string, string>)[v] ?? v;
  const responseModeLabel = (v: string) =>
    (ct.responseModes as Record<string, string>)[v] ?? v;
  const validationTypeLabel = (v: string) =>
    (ct.validationTypes as Record<string, string>)[v] ?? v;
  const runStatusLabel = (v: string) =>
    (ct.status as Record<string, string>)[v] ?? v;
  const testTypeLabel = (v: string) =>
    (ct.testTypes as Record<string, string>)[v] ?? v;
  const overallLabel = (v: string | undefined) => {
    if (!v) {
      return NONE;
    }
    const lower = v.toLowerCase();
    if (lower === "pass") {
      return ct.result.pass;
    }
    if (lower === "fail") {
      return ct.result.fail;
    }
    if (lower === "review") {
      return ct.result.review;
    }
    return v;
  };

  const parseAcceptanceCriteria = (text: string): Record<string, unknown> => {
    if (!text.trim()) {
      return {};
    }
    const parsed = parseParams(text);
    if (!parsed.ok) {
      throw new Error(ct.create.invalidJson);
    }
    return parsed.value;
  };

  useEffect(() => {
    document.title = `${t.sidebar.componentTests} - ${t.pages.appName}`;
  }, [t.pages.appName, t.sidebar.componentTests]);

  useEffect(() => {
    if (!selectedComponentId) {
      return;
    }
    const stillVisible = filteredData.some(
      (component) => component.id === selectedComponentId,
    );
    if (!stillVisible) {
      setSelectedComponentId(filteredData[0]?.id ?? null);
      setEditing(false);
    }
  }, [filteredData, selectedComponentId]);

  useEffect(() => {
    if (!selectedComponent) {
      setEditing(false);
      return;
    }
    setEditName(selectedComponent.name);
    setEditComponentCode(selectedComponent.component_code ?? "");
    setEditTransport(selectedComponent.transport);
    setEditApiUrl(selectedComponent.api_url);
    setEditApiToken(selectedComponent.api_token ?? "");
    setEditResponseMode(selectedComponent.response_mode);
    setEditSupportsStreaming(selectedComponent.supports_streaming);
    setEditValidationType(selectedComponent.validation_type);
    setEditAcceptanceCriteria(
      selectedComponent.acceptance_criteria &&
        Object.keys(selectedComponent.acceptance_criteria).length > 0
        ? JSON.stringify(selectedComponent.acceptance_criteria, null, 2)
        : "",
    );
    setEditError(null);
    // Depend on id only so a background refetch (same component, new object
    // reference) does not wipe edits in progress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedComponent?.id]);

  const resetCreateForm = () => {
    setName("");
    setComponentCode("");
    setTransport("openai_chat");
    setApiUrl("");
    setApiToken("");
    setResponseMode("blocking");
    setSupportsStreaming(false);
    setValidationType("reference_text");
    setAcceptanceCriteria("");
    setFormError(null);
  };

  const openRunDialog = (testType: ComponentTestType) => {
    setRunTestType(testType);
    setRunParams(
      testType === "effect" ? DEFAULT_EFFECT_PARAMS : DEFAULT_PERF_PARAMS,
    );
    setRunParamsError(null);
    setRunOpen(true);
  };

  const submitRun = () => {
    const parsed = parseParams(runParams);
    if (!parsed.ok) {
      setRunParamsError(parsed.error);
      return;
    }
    triggerRun.mutate(
      { testType: runTestType, params: parsed.value },
      { onSuccess: () => setRunOpen(false) },
    );
  };

  const runResultSummary = (run: ComponentTestRun): string => {
    const result = run.result;
    if (!result) {
      return NONE;
    }
    const bits = [`${ct.result.overall}: ${overallLabel(result.overall)}`];
    if (result.effect) {
      bits.push(
        `${ct.result.passed}: ${result.effect.passed}`,
        `${ct.result.failed}: ${result.effect.failed}`,
      );
    }
    if (result.perf) {
      bits.push(
        `${ct.result.successRate}: ${result.perf.success_rate ?? NONE}`,
      );
    }
    return bits.join(" · ");
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">{t.sidebar.componentTests}</h1>
      </WorkspaceHeader>
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl px-4 pt-6 md:px-8">
          <section className="to-background rounded-2xl border bg-gradient-to-r from-emerald-500/10 p-6">
            <h2 className="text-2xl font-semibold">
              {locale === "zh-CN"
                ? "先验证请求，再开展评测。"
                : "Verify requests before evaluating."}
            </h2>
            <p className="text-muted-foreground mt-3 text-sm leading-6">
              {locale === "zh-CN"
                ? "① 粘贴 cURL 并验证响应 → ② 登记组件与能力 → ③ 使用受限参数运行效果 / 性能测试。调试结果不会自动注册为组件，数据冻结与审批仍待实现。"
                : "1. Import cURL and verify the response → 2. Register the component and its capabilities → 3. Run bounded effect / performance tests. Debug requests are not automatically registered; dataset freezing and plan approval are not implemented yet."}
            </p>
          </section>
        </div>
        <div className="mx-auto w-full max-w-7xl px-4 pt-4 md:px-8">
          <RequestDebugger />
        </div>
        <div className="mx-auto flex w-full max-w-7xl flex-col gap-4 p-4 md:p-8">
          <h2 className="text-xl font-semibold">
            {locale === "zh-CN"
              ? "组件登记与运行记录"
              : "Component registry & evaluation runs"}
          </h2>

          {/* Create form */}
          <div className="grid gap-2 rounded-lg border p-4">
            <div className="font-medium">{ct.create.title}</div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={ct.create.namePlaceholder}
              />
              <Input
                value={componentCode}
                onChange={(event) => setComponentCode(event.target.value)}
                placeholder={ct.create.componentCode}
              />
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              <div className="flex flex-col gap-1">
                <span className="text-muted-foreground text-xs">
                  {ct.create.transport}
                </span>
                <select
                  className="border-input bg-background h-9 rounded-md border px-3 text-sm"
                  value={transport}
                  onChange={(event) => setTransport(event.target.value)}
                >
                  {TRANSPORTS.map((value) => (
                    <option key={value} value={value}>
                      {transportLabel(value)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-muted-foreground text-xs">
                  {ct.create.responseMode}
                </span>
                <select
                  className="border-input bg-background h-9 rounded-md border px-3 text-sm"
                  value={responseMode}
                  onChange={(event) => setResponseMode(event.target.value)}
                >
                  {RESPONSE_MODES.map((value) => (
                    <option key={value} value={value}>
                      {responseModeLabel(value)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-muted-foreground text-xs">
                  {ct.create.validationType}
                </span>
                <select
                  className="border-input bg-background h-9 rounded-md border px-3 text-sm"
                  value={validationType}
                  onChange={(event) => setValidationType(event.target.value)}
                >
                  {VALIDATION_TYPES.map((value) => (
                    <option key={value} value={value}>
                      {validationTypeLabel(value)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <Input
              value={apiUrl}
              onChange={(event) => setApiUrl(event.target.value)}
              placeholder={ct.create.apiUrlPlaceholder}
            />
            <Input
              value={apiToken}
              onChange={(event) => setApiToken(event.target.value)}
              placeholder={ct.create.apiToken}
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={supportsStreaming}
                onChange={(event) => setSupportsStreaming(event.target.checked)}
              />
              {ct.create.supportsStreaming}
            </label>
            <Textarea
              rows={3}
              value={acceptanceCriteria}
              onChange={(event) => setAcceptanceCriteria(event.target.value)}
              placeholder={ct.create.acceptanceCriteriaPlaceholder}
            />
            {formError && (
              <div className="text-destructive text-sm">{formError}</div>
            )}
            <Button
              onClick={() => {
                if (!name || !apiUrl) {
                  setFormError(ct.create.fillRequired);
                  return;
                }
                let criteria: Record<string, unknown>;
                try {
                  criteria = parseAcceptanceCriteria(acceptanceCriteria);
                } catch (error) {
                  setFormError(
                    error instanceof Error
                      ? error.message
                      : ct.create.invalidJson,
                  );
                  return;
                }
                setFormError(null);
                createComponent.mutate(
                  {
                    name,
                    component_code: componentCode.trim() || null,
                    transport,
                    api_url: apiUrl,
                    api_token: apiToken.trim() || null,
                    response_mode: responseMode,
                    supports_streaming: supportsStreaming,
                    validation_type: validationType,
                    acceptance_criteria: criteria,
                  },
                  { onSuccess: resetCreateForm },
                );
              }}
              disabled={!name || !apiUrl || createComponent.isPending}
            >
              {ct.create.submit}
            </Button>
          </div>

          {componentsQuery.error ? (
            <div className="text-destructive text-sm">
              {ct.detail.loadFailed}: {componentsQuery.error.message}
            </div>
          ) : null}

          {/* Status filter */}
          <div className="flex flex-wrap gap-2">
            <Button
              variant={statusFilter === "all" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("all")}
            >
              {ct.filters.all}
            </Button>
            <Button
              variant={statusFilter === "enabled" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("enabled")}
            >
              {ct.filters.enabled}
            </Button>
            <Button
              variant={statusFilter === "disabled" ? "default" : "outline"}
              size="sm"
              onClick={() => setStatusFilter("disabled")}
            >
              {ct.filters.disabled}
            </Button>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
            {/* Component list */}
            <div className="flex flex-col gap-3">
              {filteredData.map((component) => {
                const isSelected = selectedComponent?.id === component.id;
                return (
                  <button
                    type="button"
                    key={component.id}
                    onClick={() => setSelectedComponentId(component.id)}
                    className={cn(
                      "rounded-lg border p-4 text-left",
                      isSelected ? "border-foreground" : "border-border",
                    )}
                  >
                    <div className="font-medium">{component.name}</div>
                    <div className="text-muted-foreground text-sm">
                      {transportLabel(component.transport)} ·{" "}
                      {component.enabled
                        ? ct.detail.enabled
                        : ct.detail.disabled}
                    </div>
                  </button>
                );
              })}
              {filteredData.length === 0 && (
                <div className="text-muted-foreground text-sm">
                  {ct.detail.noSelection}
                </div>
              )}
            </div>

            {/* Detail panel */}
            <div className="rounded-lg border p-4">
              {selectedComponent ? (
                <div className="flex flex-col gap-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-lg font-semibold">
                      {selectedComponent.name}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditing((value) => !value)}
                    >
                      {editing ? ct.actions.cancelEdit : ct.actions.edit}
                    </Button>
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {ct.detail.transport}:{" "}
                    {transportLabel(selectedComponent.transport)}
                  </div>
                  <div className="text-muted-foreground text-sm break-all">
                    {ct.detail.apiUrl}: {selectedComponent.api_url}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {ct.detail.responseMode}:{" "}
                    {responseModeLabel(selectedComponent.response_mode)}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {ct.detail.validationType}:{" "}
                    {validationTypeLabel(selectedComponent.validation_type)}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {ct.detail.status}:{" "}
                    {selectedComponent.enabled
                      ? ct.detail.enabled
                      : ct.detail.disabled}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {ct.detail.updatedAt}:{" "}
                    {formatTimestamp(selectedComponent.updated_at, locale)}
                  </div>

                  {editing ? (
                    <div className="flex flex-col gap-2 rounded-lg border p-3">
                      <Input
                        value={editName}
                        onChange={(event) => setEditName(event.target.value)}
                        placeholder={ct.create.namePlaceholder}
                      />
                      <Input
                        value={editComponentCode}
                        onChange={(event) =>
                          setEditComponentCode(event.target.value)
                        }
                        placeholder={ct.create.componentCode}
                      />
                      <div className="grid grid-cols-2 gap-2">
                        <select
                          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
                          value={editTransport}
                          onChange={(event) =>
                            setEditTransport(event.target.value)
                          }
                        >
                          {TRANSPORTS.map((value) => (
                            <option key={value} value={value}>
                              {transportLabel(value)}
                            </option>
                          ))}
                        </select>
                        <select
                          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
                          value={editValidationType}
                          onChange={(event) =>
                            setEditValidationType(event.target.value)
                          }
                        >
                          {VALIDATION_TYPES.map((value) => (
                            <option key={value} value={value}>
                              {validationTypeLabel(value)}
                            </option>
                          ))}
                        </select>
                      </div>
                      <Input
                        value={editApiUrl}
                        onChange={(event) => setEditApiUrl(event.target.value)}
                        placeholder={ct.create.apiUrlPlaceholder}
                      />
                      <Input
                        value={editApiToken}
                        onChange={(event) =>
                          setEditApiToken(event.target.value)
                        }
                        placeholder={ct.create.apiToken}
                      />
                      <div className="grid grid-cols-2 gap-2">
                        <select
                          className="border-input bg-background h-9 rounded-md border px-3 text-sm"
                          value={editResponseMode}
                          onChange={(event) =>
                            setEditResponseMode(event.target.value)
                          }
                        >
                          {RESPONSE_MODES.map((value) => (
                            <option key={value} value={value}>
                              {responseModeLabel(value)}
                            </option>
                          ))}
                        </select>
                        <label className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={editSupportsStreaming}
                            onChange={(event) =>
                              setEditSupportsStreaming(event.target.checked)
                            }
                          />
                          {ct.create.supportsStreaming}
                        </label>
                      </div>
                      <Textarea
                        rows={3}
                        value={editAcceptanceCriteria}
                        onChange={(event) =>
                          setEditAcceptanceCriteria(event.target.value)
                        }
                        placeholder={ct.create.acceptanceCriteriaPlaceholder}
                      />
                      {editError && (
                        <div className="text-destructive text-sm">
                          {editError}
                        </div>
                      )}
                      <Button
                        size="sm"
                        onClick={() => {
                          let criteria: Record<string, unknown>;
                          try {
                            criteria = parseAcceptanceCriteria(
                              editAcceptanceCriteria,
                            );
                          } catch (error) {
                            setEditError(
                              error instanceof Error
                                ? error.message
                                : ct.create.invalidJson,
                            );
                            return;
                          }
                          setEditError(null);
                          updateComponent.mutate({
                            name: editName,
                            component_code: editComponentCode.trim() || null,
                            transport: editTransport,
                            api_url: editApiUrl,
                            api_token: editApiToken.trim() || null,
                            response_mode: editResponseMode,
                            supports_streaming: editSupportsStreaming,
                            validation_type: editValidationType,
                            acceptance_criteria: criteria,
                          });
                        }}
                        disabled={updateComponent.isPending}
                      >
                        {ct.edit.submit}
                      </Button>
                    </div>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openRunDialog("effect")}
                      >
                        {ct.actions.runEffect}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openRunDialog("perf")}
                      >
                        {ct.actions.runPerf}
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setDeleteOpen(true)}
                      >
                        {ct.actions.delete}
                      </Button>
                    </div>
                  )}

                  {/* Runs list */}
                  <div className="text-muted-foreground text-sm">
                    {runs.length === 1
                      ? ct.detail.runsCountOne.replace(
                          "{count}",
                          String(runs.length),
                        )
                      : ct.detail.runsCount.replace(
                          "{count}",
                          String(runs.length),
                        )}
                  </div>
                  <div className="flex flex-col gap-2">
                    {runs.length > 0 ? (
                      runs.map((run) => (
                        <div
                          key={run.id}
                          className="rounded-md border p-3 text-sm"
                        >
                          <div className="font-medium">
                            {testTypeLabel(run.test_type)} ·{" "}
                            {runStatusLabel(run.status)}
                          </div>
                          <div className="text-muted-foreground text-xs">
                            {runResultSummary(run)}
                          </div>
                          <div className="text-muted-foreground text-xs">
                            {formatTimestamp(run.created_at, locale)}
                          </div>
                          {run.status === "completed" && (
                            <Button
                              variant="ghost"
                              size="sm"
                              className="mt-1 h-6 px-2 text-xs"
                              onClick={() => setReportRunId(run.id)}
                            >
                              {ct.result.viewReport}
                            </Button>
                          )}
                          {run.error && (
                            <div className="text-destructive text-xs">
                              {run.error}
                            </div>
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="text-muted-foreground text-sm">
                        {ct.detail.noRuns}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="text-muted-foreground text-sm">
                  {ct.detail.noSelection}
                </div>
              )}
            </div>
          </div>
        </div>
      </WorkspaceBody>

      {/* Delete confirm dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{ct.actions.delete}</DialogTitle>
            <DialogDescription>{ct.deleteConfirm}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteComponent.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (selectedComponent) {
                  deleteComponent.mutate(selectedComponent.id, {
                    onSuccess: () => setDeleteOpen(false),
                  });
                }
              }}
              disabled={deleteComponent.isPending}
            >
              {deleteComponent.isPending ? t.common.loading : ct.actions.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Run trigger dialog */}
      <Dialog open={runOpen} onOpenChange={setRunOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{testTypeLabel(runTestType)}</DialogTitle>
            <DialogDescription>{ct.result.report}</DialogDescription>
          </DialogHeader>
          <Textarea
            rows={8}
            className="font-mono text-xs"
            value={runParams}
            onChange={(event) => setRunParams(event.target.value)}
          />
          {runParamsError && (
            <div className="text-destructive text-sm">{runParamsError}</div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setRunOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button onClick={submitRun} disabled={triggerRun.isPending}>
              {triggerRun.isPending ? t.common.loading : ct.create.submit}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Report dialog */}
      <Dialog
        open={Boolean(reportRunId)}
        onOpenChange={(open) => !open && setReportRunId(null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{ct.result.report}</DialogTitle>
          </DialogHeader>
          <pre className="bg-muted max-h-[60vh] overflow-auto rounded-md border p-4 text-xs">
            {reportQuery.data
              ? JSON.stringify(reportQuery.data, null, 2)
              : ct.result.noResult}
          </pre>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReportRunId(null)}>
              {t.common.cancel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </WorkspaceContainer>
  );
}
