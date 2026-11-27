"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useAuth } from "@/core/auth/AuthProvider";
import type { ProjectComponent } from "@/core/datasets/registry-types";
import { evaluationApi } from "@/core/evaluation/api";
import {
  createPerformanceRun,
  createPerformanceScenario,
  getPerformanceRun,
  listPerformanceRuns,
  listPerformanceScenarios,
  type PerformanceRun,
  type PerformanceScenario,
  type PerformanceProfile,
} from "@/core/evaluation/performance-results-api";
import type { FrozenPlan } from "@/core/evaluation/plan-types";
import type { ProjectList } from "@/core/evaluation/result-types";
import { listResultProjects } from "@/core/evaluation/results-api";
import { useI18n } from "@/core/i18n/hooks";

const initialProfile: PerformanceProfile = {
  concurrency: 1,
  measured_request_count: 1,
  warmup_request_count: 0,
  duration_limit_seconds: null,
  request_timeout_ms: 10_000,
  max_in_flight: 1,
  wall_time_limit_seconds: 30,
  drain_limit_seconds: 10,
  max_request_bytes: 1_048_576,
  max_response_bytes: 1_048_576,
  max_total_bytes: 2_097_152,
};

const profileFields: Array<{
  key: keyof PerformanceProfile;
  min: number;
  max: number;
}> = [
  { key: "concurrency", min: 1, max: 64 },
  { key: "warmup_request_count", min: 0, max: 1_000 },
  { key: "request_timeout_ms", min: 100, max: 300_000 },
  { key: "max_in_flight", min: 1, max: 64 },
  { key: "wall_time_limit_seconds", min: 1, max: 7_200 },
  { key: "drain_limit_seconds", min: 1, max: 300 },
  { key: "max_request_bytes", min: 1, max: 10_000_000 },
  { key: "max_response_bytes", min: 1, max: 10_000_000 },
  { key: "max_total_bytes", min: 1, max: 1_000_000_000 },
];

const inputStyle = "bg-background w-full rounded-md border px-3 py-2 text-sm";

export default function PerformanceWorkbench() {
  const { user } = useAuth();
  return <PerformanceWorkbenchContent key={user?.id ?? "anonymous"} />;
}

function PerformanceWorkbenchContent() {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const t = (en: string, zhText: string) => (zh ? zhText : en);
  const [projects, setProjects] = useState<ProjectList["projects"]>([]);
  const [components, setComponents] = useState<ProjectComponent[]>([]);
  const [plans, setPlans] = useState<FrozenPlan[]>([]);
  const [scenarios, setScenarios] = useState<PerformanceScenario[]>([]);
  const [runRows, setRunRows] = useState<PerformanceRun[]>([]);
  const [runCursor, setRunCursor] = useState<string | null>(null);
  const [runListLoaded, setRunListLoaded] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [componentId, setComponentId] = useState("");
  const [planId, setPlanId] = useState("");
  const [scenario, setScenario] = useState<PerformanceScenario | null>(null);
  const [profile, setProfile] = useState(initialProfile);
  const [freezeConfirmed, setFreezeConfirmed] = useState(false);
  const [runConfirmed, setRunConfirmed] = useState(false);
  const [scenarioWriteUncertain, setScenarioWriteUncertain] = useState(false);
  const [createdRun, setCreatedRun] = useState<PerformanceRun | null>(null);
  const [pendingRun, setPendingRun] = useState<{
    projectId: string;
    id: string;
  } | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  const [componentsLoaded, setComponentsLoaded] = useState(false);
  const [plansLoaded, setPlansLoaded] = useState(false);
  const epoch = useRef(0);
  const alive = useRef(true);
  const lock = useRef(false);

  const selectedPlan = plans.find(
    (plan) =>
      plan.id === planId && plan.definition.limits.mode === "performance",
  );
  const validProfile = Boolean(
    selectedPlan &&
    profile.concurrency >= 1 &&
    profile.concurrency <= 64 &&
    profile.measured_request_count ===
      selectedPlan.definition.limits.request_count &&
    Number.isInteger(profile.warmup_request_count) &&
    profile.warmup_request_count >= 0 &&
    profile.warmup_request_count <= 1_000 &&
    (profile.duration_limit_seconds === null ||
      (Number.isInteger(profile.duration_limit_seconds) &&
        profile.duration_limit_seconds >= 1 &&
        profile.duration_limit_seconds <= 3_600)) &&
    Number.isInteger(profile.request_timeout_ms) &&
    profile.request_timeout_ms >= 100 &&
    profile.request_timeout_ms <= 300_000 &&
    Number.isInteger(profile.max_in_flight) &&
    profile.max_in_flight >= profile.concurrency &&
    profile.max_in_flight <= 64 &&
    Number.isInteger(profile.wall_time_limit_seconds) &&
    profile.wall_time_limit_seconds >= 1 &&
    profile.wall_time_limit_seconds <= 7_200 &&
    Number.isInteger(profile.drain_limit_seconds) &&
    profile.drain_limit_seconds >= 1 &&
    profile.drain_limit_seconds <= 300 &&
    profile.drain_limit_seconds <= profile.wall_time_limit_seconds &&
    profile.request_timeout_ms <= profile.wall_time_limit_seconds * 1_000 &&
    Number.isInteger(profile.max_request_bytes) &&
    profile.max_request_bytes >= 1 &&
    profile.max_request_bytes <= 10_000_000 &&
    Number.isInteger(profile.max_response_bytes) &&
    profile.max_response_bytes >= 1 &&
    profile.max_response_bytes <= 10_000_000 &&
    Number.isInteger(profile.max_total_bytes) &&
    profile.max_total_bytes >=
      profile.max_request_bytes + profile.max_response_bytes &&
    profile.max_total_bytes <= 1_000_000_000,
  );

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      epoch.current += 1;
    };
  }, []);

  function clearConfirmations() {
    setFreezeConfirmed(false);
    setRunConfirmed(false);
    setNotice("");
  }

  function scopeChanged() {
    epoch.current += 1;
    lock.current = false;
    setBusy("");
    setError("");
    setNotice("");
    setComponents([]);
    setPlans([]);
    setScenarios([]);
    setRunRows([]);
    setRunCursor(null);
    setRunListLoaded(false);
    setComponentsLoaded(false);
    setPlansLoaded(false);
    setScenarioWriteUncertain(false);
    setComponentId("");
    setPlanId("");
    setScenario(null);
    setProfile(initialProfile);
    setCreatedRun(null);
    clearConfirmations();
  }

  async function runAction(name: string, action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true;
    const token = epoch.current;
    setBusy(name);
    setError("");
    setNotice("");
    try {
      await action();
    } catch {
      if (alive.current && token === epoch.current) {
        if (name === "freeze") setScenarioWriteUncertain(true);
        setError(
          t(
            "Operation could not be confirmed. Inspect existing records before any new write; no automatic retry was made.",
            "无法确认操作结果。请先检查已有记录；未自动重试写入。",
          ),
        );
      }
    } finally {
      lock.current = false;
      if (alive.current && token === epoch.current) setBusy("");
    }
  }

  function loadProjects() {
    void runAction("projects", async () => {
      const result = await listResultProjects();
      if (!alive.current) return;
      setProjects(result.projects);
      setProjectsLoaded(true);
      scopeChanged();
    });
  }

  function loadRunLedgers(cursor?: string) {
    if (!projectId) return;
    const projectForRead = projectId;
    const scopeEpoch = epoch.current;
    void runAction("runs", async () => {
      const result = await listPerformanceRuns(projectForRead, {
        limit: 50,
        ...(cursor ? { cursor } : {}),
      });
      if (
        !alive.current ||
        scopeEpoch !== epoch.current ||
        projectId !== projectForRead
      )
        return;
      setRunRows((current) => {
        const next = cursor ? [...current, ...result.items] : result.items;
        return Array.from(new Map(next.map((run) => [run.id, run])).values());
      });
      setRunCursor(result.next_cursor);
      setRunListLoaded(true);
    });
  }

  function loadComponents() {
    if (!projectId) return;
    void runAction("components", async () => {
      const result = await evaluationApi<{ components: ProjectComponent[] }>(
        `evaluation/projects/${encodeURIComponent(projectId)}/components`,
      );
      if (!alive.current) return;
      scopeChanged();
      setProjectId((current) => current);
      setComponents(result.components);
      setComponentsLoaded(true);
    });
  }

  function loadPlansAndScenarios() {
    if (!projectId || !componentId) return;
    void runAction("plans", async () => {
      const base = `evaluation/projects/${encodeURIComponent(projectId)}/components/${encodeURIComponent(componentId)}`;
      const [planResult, scenarioResult] = await Promise.all([
        evaluationApi<{ plans: FrozenPlan[] }>(`${base}/plans`),
        listPerformanceScenarios(projectId, componentId),
      ]);
      if (!alive.current) return;
      setPlans(
        planResult.plans.filter(
          (plan) => plan.scope === "frozen_definition_only",
        ),
      );
      setScenarios(scenarioResult.scenarios);
      setPlanId("");
      setScenario(null);
      setProfile(initialProfile);
      setPlansLoaded(true);
      setScenarioWriteUncertain(false);
      clearConfirmations();
    });
  }

  function changeProject(value: string) {
    scopeChanged();
    setProjectId(value);
    setProjectsLoaded(true);
  }

  function changeComponent(value: string) {
    epoch.current += 1;
    setComponentId(value);
    setPlans([]);
    setScenarios([]);
    setPlansLoaded(false);
    setScenarioWriteUncertain(false);
    setPlanId("");
    setScenario(null);
    setProfile(initialProfile);
    setCreatedRun(null);
    clearConfirmations();
    setError("");
  }

  function changePlan(value: string) {
    const next = plans.find(
      (plan) =>
        plan.id === value && plan.definition.limits.mode === "performance",
    );
    setPlanId(next?.id ?? "");
    setProfile({
      ...initialProfile,
      measured_request_count: next?.definition.limits.request_count ?? 1,
    });
    setScenario(null);
    setCreatedRun(null);
    clearConfirmations();
  }

  function editProfile(key: keyof PerformanceProfile, value: number | null) {
    setProfile((current) => ({ ...current, [key]: value }));
    setScenario(null);
    setCreatedRun(null);
    clearConfirmations();
  }

  function selectScenario(row: PerformanceScenario) {
    const frozenPlan = plans.find(
      (plan) =>
        plan.id === row.plan_id &&
        plan.definition.limits.mode === "performance",
    );
    if (!frozenPlan) return;
    setPlanId(frozenPlan.id);
    setProfile(row.definition.profile);
    setScenario(row);
    setCreatedRun(null);
    clearConfirmations();
  }

  function freezeScenario() {
    if (
      !projectId ||
      !componentId ||
      !selectedPlan ||
      !validProfile ||
      !freezeConfirmed ||
      busy
    )
      return;
    void runAction("freeze", async () => {
      const result = await createPerformanceScenario(projectId, componentId, {
        plan_id: selectedPlan.id,
        profile,
        confirmed: true,
      });
      if (!alive.current) return;
      setScenario(result);
      setScenarios((current) => [result, ...current]);
      setFreezeConfirmed(false);
      setRunConfirmed(false);
      setNotice(
        t(
          "Scenario frozen immutably. This is only a definition; no Worker or target call was started.",
          "性能场景已不可变冻结。这只是定义；未启动 Worker 或调用目标。",
        ),
      );
    });
  }

  function createLedger() {
    if (!projectId || !scenario || !runConfirmed || busy || pendingRun) return;
    const runId = Array.from(
      globalThis.crypto.getRandomValues(new Uint8Array(16)),
    )
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    const projectForWrite = projectId;
    const scenarioForWrite = scenario;
    setPendingRun({ projectId: projectForWrite, id: runId });
    setRunConfirmed(false);
    void runAction("run", async () => {
      const result = await createPerformanceRun(projectForWrite, {
        run_id: runId,
        scenario_id: scenarioForWrite.id,
        scenario_hash: scenarioForWrite.definition_hash,
        confirmed: true,
      });
      if (!alive.current) return;
      setPendingRun(null);
      setCreatedRun(result);
      setNotice(
        t(
          "Ledger only: this did not start a Worker, dispatch requests, measure a target, or produce target metrics.",
          "仅创建运行台账：未启动 Worker、派发请求、测量目标或产生目标指标。",
        ),
      );
    }).catch(() => {
      // Keep the exact pre-generated ID for explicit GET-only reconciliation.
    });
  }

  function reconcileRunId(exactProjectId: string, exactRunId: string) {
    if (busy) return;
    const scopeEpoch = epoch.current;
    void runAction("reconcile", async () => {
      const result = await getPerformanceRun(exactProjectId, exactRunId);
      if (!alive.current || scopeEpoch !== epoch.current) return;
      setCreatedRun(result);
      setPendingRun((current) =>
        current?.projectId === exactProjectId && current.id === exactRunId
          ? null
          : current,
      );
      setRunConfirmed(false);
      setNotice(
        t(
          "The original run ID was reconciled. Ledger only; no Worker or target request was started.",
          "已按原运行ID对账。仅为台账；未启动Worker或目标请求。",
        ),
      );
    });
  }

  function reconcileRun() {
    if (!pendingRun || busy) return;
    reconcileRunId(pendingRun.projectId, pendingRun.id);
  }

  const freezeEnabled = Boolean(
    selectedPlan &&
    validProfile &&
    freezeConfirmed &&
    !busy &&
    !scenarioWriteUncertain,
  );
  const runEnabled = Boolean(scenario && runConfirmed && !busy && !pendingRun);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader>
        <h1 className="text-lg font-semibold">
          {t("Performance workbench", "????????")}
        </h1>
      </WorkspaceHeader>
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-8">
          <p className="text-muted-foreground text-sm leading-6">
            {t(
              "Freeze bounded performance scenarios and create run ledgers. This page does not execute load tests.",
              "???????????????????????????????????????????",
            )}
          </p>
          <div
            role="status"
            className="rounded-lg border border-amber-500/50 bg-amber-50/50 p-4 text-sm leading-6 dark:bg-amber-950/20"
          >
            {t(
              "Creating a scenario or run ledger does not start a Worker, dispatch requests, measure a target, or produce target metrics. No admission, polling, or evidence calls are made here.",
              "创建场景或运行台账不会启动 Worker、派发请求、测量目标或产生目标指标。本页不会调用准入、轮询或证据接口。",
            )}
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          {notice && (
            <p role="status" className="text-sm">
              {notice}
            </p>
          )}
          {scenarioWriteUncertain && (
            <p role="alert" className="text-destructive text-sm">
              {t(
                "Scenario write outcome is uncertain. Do not submit again; explicitly reload plans and scenarios to inspect the frozen list.",
                "场景写入结果未知。不要再次提交；请显式重新加载计划与场景并检查冻结列表。",
              )}
            </p>
          )}
          {pendingRun && (
            <div className="space-y-2 rounded-md border p-3 text-sm">
              <p>
                {t(
                  "Run creation is uncertain. Do not submit again. Reconcile only this exact ID:",
                  "运行创建结果未知。不要再次提交。仅对账此精确 ID：",
                )}
              </p>
              <code>{pendingRun.id}</code>
              <Button
                type="button"
                variant="outline"
                disabled={Boolean(busy)}
                onClick={reconcileRun}
              >
                {t("Reconcile run ID", "按运行 ID 对账")}
              </Button>
            </div>
          )}

          <section
            className="space-y-4 rounded-xl border p-5"
            aria-labelledby="performance-scope-heading"
          >
            <h2 id="performance-scope-heading" className="font-semibold">
              {t("Owner-scoped inputs", "项目范围输入")}
            </h2>
            <Button
              type="button"
              variant="outline"
              disabled={Boolean(busy)}
              onClick={loadProjects}
            >
              {t("Load projects", "加载项目")}
            </Button>
            {projectsLoaded && (
              <label className="block space-y-1 text-sm">
                <span>{t("Project", "项目")}</span>
                <select
                  className={inputStyle}
                  aria-label={t("Project", "项目")}
                  value={projectId}
                  onChange={(event) => changeProject(event.target.value)}
                >
                  <option value="">{t("Select project", "选择项目")}</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {projectId && (
              <Button
                type="button"
                variant="outline"
                disabled={Boolean(busy)}
                onClick={loadComponents}
              >
                {t("Load components", "加载组件")}
              </Button>
            )}
            {componentsLoaded && (
              <label className="block space-y-1 text-sm">
                <span>{t("Component", "组件")}</span>
                <select
                  className={inputStyle}
                  aria-label={t("Component", "组件")}
                  value={componentId}
                  onChange={(event) => changeComponent(event.target.value)}
                >
                  <option value="">{t("Select component", "选择组件")}</option>
                  {components.map((component) => (
                    <option key={component.id} value={component.id}>
                      {component.name_at_link}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {componentId && (
              <Button
                type="button"
                variant="outline"
                disabled={Boolean(busy)}
                onClick={loadPlansAndScenarios}
              >
                {t("Load plans and scenarios", "加载计划与场景")}
              </Button>
            )}
            {plansLoaded && (
              <label className="block space-y-1 text-sm">
                <span>{t("Frozen performance plan", "冻结的性能计划")}</span>
                <select
                  className={inputStyle}
                  aria-label={t("Frozen performance plan", "冻结的性能计划")}
                  value={planId}
                  onChange={(event) => changePlan(event.target.value)}
                >
                  <option value="">
                    {t("Select performance plan", "选择性能计划")}
                  </option>
                  {plans
                    .filter(
                      (plan) => plan.definition.limits.mode === "performance",
                    )
                    .map((plan) => (
                      <option key={plan.id} value={plan.id}>
                        {plan.version_label} · {plan.id}
                      </option>
                    ))}
                </select>
              </label>
            )}
            {projectId && (
              <section
                className="space-y-4 rounded-xl border p-5"
                aria-labelledby="performance-runs-heading"
              >
                <h2 id="performance-runs-heading" className="font-semibold">
                  {t("Existing run ledgers", "已有运行台账")}
                </h2>
                <p className="text-muted-foreground text-sm">
                  {t(
                    "Load is explicit. Reconciliation reads each exact run ID once and never creates or dispatches a run.",
                    "列表需显式加载。对账仅按精确运行ID读取、不会创建或派发运行。",
                  )}
                </p>
                <Button
                  type="button"
                  variant="outline"
                  disabled={Boolean(busy)}
                  onClick={() => loadRunLedgers()}
                >
                  {t("Load run ledgers", "加载运行台账")}
                </Button>
                {runListLoaded && runRows.length === 0 && (
                  <p className="text-sm">
                    {t("No run ledgers found.", "没有找到运行台账。")}
                  </p>
                )}
                {runRows.length > 0 && (
                  <ul className="space-y-2">
                    {runRows.map((run) => (
                      <li
                        key={run.id}
                        className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm"
                      >
                        <div className="min-w-0 space-y-1">
                          <code className="break-all">{run.id}</code>
                          <p className="text-muted-foreground">
                            {run.status} · {run.scenario_id} ·{" "}
                            {run.population_count} {t("requests", "个请求")}
                          </p>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          disabled={Boolean(busy)}
                          onClick={() => reconcileRunId(projectId, run.id)}
                        >
                          {t("Reconcile exact run ID", "按精确运行ID对账")}
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
                {runCursor && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={Boolean(busy)}
                    onClick={() => loadRunLedgers(runCursor)}
                  >
                    {t("Load more run ledgers", "加载更多运行台账")}
                  </Button>
                )}
              </section>
            )}

            {selectedPlan && (
              <p className="text-sm">
                {selectedPlan.definition.limits.request_count}{" "}
                {t("measured requests", "个测量请求（来自冻结计划）")}
              </p>
            )}
          </section>

          {selectedPlan && (
            <section
              className="space-y-4 rounded-xl border p-5"
              aria-labelledby="performance-profile-heading"
            >
              <h2 id="performance-profile-heading" className="font-semibold">
                {t("Bounded scenario profile", "有界场景配置")}
              </h2>
              <p className="text-muted-foreground text-sm">
                {t(
                  "Measured request count is fixed by the frozen plan and cannot be increased here.",
                  "测量请求数固定来自冻结计划，不能在此增加。",
                )}
              </p>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {profileFields.map(({ key, min, max }) => (
                  <label className="space-y-1 text-sm" key={key}>
                    <span>
                      {key
                        .replaceAll("_", " ")
                        .replace(/^./, (char) => char.toUpperCase())}
                    </span>
                    <input
                      className={inputStyle}
                      aria-label={
                        key === "max_in_flight"
                          ? "Max in flight"
                          : key
                              .replaceAll("_", " ")
                              .replace(/^./, (char) => char.toUpperCase())
                      }
                      type="number"
                      min={min}
                      max={max}
                      step={1}
                      value={profile[key]!}
                      onChange={(event) =>
                        editProfile(key, Number(event.target.value))
                      }
                    />
                  </label>
                ))}
                <label className="space-y-1 text-sm">
                  <span>
                    {t(
                      "Duration limit seconds (optional)",
                      "持续时间上限秒（可选）",
                    )}
                  </span>
                  <input
                    className={inputStyle}
                    aria-label="Duration limit seconds"
                    type="number"
                    min={1}
                    max={3600}
                    value={profile.duration_limit_seconds ?? ""}
                    onChange={(event) =>
                      editProfile(
                        "duration_limit_seconds",
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                      )
                    }
                  />
                </label>
                <label className="space-y-1 text-sm">
                  <span>
                    {t(
                      "Measured requests (frozen plan)",
                      "测量请求数（冻结计划）",
                    )}
                  </span>
                  <input
                    className={inputStyle}
                    aria-label="Measured requests"
                    type="number"
                    value={profile.measured_request_count}
                    readOnly
                  />
                </label>
              </div>
              {!validProfile && (
                <p role="alert" className="text-destructive text-sm">
                  {t(
                    "Profile bounds are inconsistent. Check concurrency, deadlines, and byte budgets.",
                    "配置超出边界或不一致。请检查并发、截止时间和字节预算。",
                  )}
                </p>
              )}
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={freezeConfirmed}
                  onChange={(event) => setFreezeConfirmed(event.target.checked)}
                />
                <span>
                  {t(
                    "I confirm freezing this immutable scenario definition.",
                    "我确认冻结此不可变场景定义。",
                  )}
                </span>
              </label>
              <Button
                type="button"
                disabled={!freezeEnabled}
                onClick={freezeScenario}
              >
                {t("Freeze scenario", "冻结场景")}
              </Button>
            </section>
          )}

          {plansLoaded && scenarios.length > 0 && (
            <section
              className="space-y-3 rounded-xl border p-5"
              aria-labelledby="frozen-scenarios-heading"
            >
              <h2 id="frozen-scenarios-heading" className="font-semibold">
                {t("Frozen scenarios", "已冻结场景")}
              </h2>
              <ul className="space-y-2">
                {scenarios.map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      className="text-left underline underline-offset-4"
                      onClick={() => selectScenario(row)}
                    >
                      {row.id} · {row.definition_hash}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {scenario && (
            <section
              className="space-y-4 rounded-xl border p-5"
              aria-labelledby="performance-ledger-heading"
            >
              <h2 id="performance-ledger-heading" className="font-semibold">
                {t("Run ledger", "运行台账")}
              </h2>
              <p className="text-sm">
                {scenario.id} · SHA-256 {scenario.definition_hash}
              </p>
              <p className="text-muted-foreground text-sm">
                {t(
                  "Ledger only. It does not start a Worker or dispatch requests.",
                  "仅创建台账，不会启动 Worker 或派发请求。",
                )}
              </p>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  aria-label={t(
                    "I confirm creating a run ledger",
                    "我确认创建运行台账",
                  )}
                  checked={runConfirmed}
                  onChange={(event) => setRunConfirmed(event.target.checked)}
                />
                <span>
                  {t(
                    "I confirm creating a run ledger for this exact frozen scenario.",
                    "我确认仅为此冻结场景创建运行台账。",
                  )}
                </span>
              </label>
              <Button
                type="button"
                disabled={!runEnabled}
                onClick={createLedger}
              >
                {t("Create run ledger", "创建运行台账")}
              </Button>
              {createdRun && (
                <div className="space-y-2 text-sm">
                  <p>
                    {t("Ledger only", "仅台账")} · {createdRun.id}
                  </p>
                  <Link
                    className="underline underline-offset-4"
                    href="/workspace/performance-results"
                  >
                    {t(
                      "Browse run results and applicability",
                      "浏览运行结果与适用性",
                    )}
                  </Link>
                </div>
              )}
            </section>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
